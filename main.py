import json
import sys
import re
import os
import subprocess
import pdb

from ethereum.utils import decode_hex, parse_int_or_hex, sha3, to_string, \
	remove_0x_head, encode_hex, big_endian_to_int
	
import ethereum.transactions as transactions

import itertools
	
from evmlab import genesis as gen
from evmlab import gethvm
from evmlab import compiler as c

from evmlab import opcodes

import io
from contextlib import redirect_stderr, redirect_stdout

print("opcodes:", opcodes.opcodes)

OPCODES = {}
op_keys = opcodes.opcodes.keys()
for op_key in op_keys:
	name = opcodes.opcodes[op_key][0]
	OPCODES[name] = op_key

print("OPCODES:", OPCODES)



FORK_CONFIG = 'EIP158'


TESTS_PATH = '/home/ubuntu/tests'

JS_PATH = '/home/ubuntu/og/ethereumjs-vm'

# cpp wants path "/Users/macbook/dev_metropolis/tests-schema/jwasinger-rebase/tests"

PRESTATE_TMP_FILE = 'prestate.json'

TESTETH = '/home/ubuntu/cdetrio/cpp-ethereum/build/test/testeth'

# ./testeth -t StateTestsGeneral/stStackTests -- --singletest shallowStack --jsontrace '{ "disableStorage" : true }' --singlenet EIP158 -d 63 -g 0 -v 0 --testpath "/Users/macbook/dev_metropolis/tests-schema/jwasinger-rebase/tests"


#def opNameToNumber(op_name):
#	return OPCODES[name]



def getAllFiles():
	all_files = []
	for subdir, dirs, files in os.walk(TESTS_PATH):
		for file in files:
			test_file = os.path.join(subdir, file)
			if test_file.endswith('.json'):
				all_files.append(test_file)
	return all_files



def convertGeneralTest(test_file):
	with open(test_file) as json_data:
		print("test_file:", test_file)
		print("path string:", test_file.split(os.sep))
		test_folder = test_file.split(os.sep)[-2]
		print("test_folder:", test_folder)
		
		general_test = json.load(json_data)
		#print("general_test:", general_test)
		for test_name in general_test:
			# should only be one test_name per file
			print("test_name:", test_name)
			prestate = {}
			prestate['env'] = general_test[test_name]['env']
			prestate['pre'] = general_test[test_name]['pre']
			#print("prestate:", prestate)
			general_tx = general_test[test_name]['transaction']
			transactions = []
			for test_i in general_test[test_name]['post'][FORK_CONFIG]:
				test_tx = general_tx.copy()
				#print("general_tx:", general_tx)
				#print("test_i:", test_i)
				d_i = test_i['indexes']['data']
				g_i = test_i['indexes']['gas']
				v_i = test_i['indexes']['value']
				test_tx['data'] = general_tx['data'][d_i]
				test_tx['gasLimit'] = general_tx['gasLimit'][g_i]
				test_tx['value'] = general_tx['value'][v_i]
				#print("test_tx:", test_tx)
				test_dgv = (d_i, g_i, v_i)
				transactions.append((test_tx, test_dgv))
	return prestate, transactions



def getIntrinsicGas(test_tx):
	tx = transactions.Transaction(
		nonce=parse_int_or_hex(test_tx['nonce'] or b"0"),
		gasprice=parse_int_or_hex(test_tx['gasPrice'] or b"0"),
		startgas=parse_int_or_hex(test_tx['gasLimit'] or b"0"),
		to=decode_hex(remove_0x_head(test_tx['to'])),
		value=parse_int_or_hex(test_tx['value'] or b"0"),
		data=decode_hex(remove_0x_head(test_tx['data'])))
	
	return tx.intrinsic_gas_used


def getTxSender(test_tx):
	tx = transactions.Transaction(
		nonce=parse_int_or_hex(test_tx['nonce'] or b"0"),
		gasprice=parse_int_or_hex(test_tx['gasPrice'] or b"0"),
		startgas=parse_int_or_hex(test_tx['gasLimit'] or b"0"),
		to=decode_hex(remove_0x_head(test_tx['to'])),
		value=parse_int_or_hex(test_tx['value'] or b"0"),
		data=decode_hex(remove_0x_head(test_tx['data'])))
	if 'secretKey' in test_tx:
		tx.sign(decode_hex(remove_0x_head(test_tx['secretKey'])))
	return encode_hex(tx.sender)




def outputs(stdouts):
	import json
	finished = False
	while not finished:
		items = []
		for outp in stdouts:
			if outp == "":
				items.append({})
				finished = True
			else:
				outp = outp.strip()
				try:
					items.append(json.loads(outp))
				except ValueError:
					print("Invalid json: %s" % outp)
					items.append({})
		yield items

def canon(str):
	if str in [None, "0x", ""]:
		return ""
	if str[:2] == "0x":
		return str
	return "0x" + str

def toText(op):
	if len(op.keys()) == 0:
		return "END"
	if 'pc' in op.keys():
		#return "pc {pc} op {op} gas {gas} cost {gasCost} depth {depth} stack {stack}".format(**op)
		return "pc {pc} op {op} gas {gas} depth {depth} stack {stack}".format(**op)
	elif 'output' in op.keys():
		op['output'] = canon(op['output'])
		return "output {output} gasUsed {gasUsed}".format(**op)
	return "N/A"



def bstrToInt(b_str):
	b_str = b_str.replace("b", "")
	b_str = b_str.replace("'", "")
	return int(b_str)

def bstrToHex(b_str):
	return '0x{0:01x}'.format(bstrToInt(b_str))

def toHexQuantities(vals):
	quantities = []
	for val in vals:
		val_int = parse_int_or_hex(val)
		quantities.append('0x{0:01x}'.format(val_int))
	return quantities

def doJs():
  cmd_js = 'node'
  cmd_js += ' '+JS_PATH+'/tests/tester.js'
  cmd_js += ' -s'
  cmd_js +=' --JSONTrace'
  #cmd_js += ' --testpath '+TESTS_PATH
  #cmd_js += ' --test '+test_subfolder+'/'+test_name+'.json'

  js_p = subprocess.Popen(cmd_js, shell=True, stdout=subprocess.PIPE, close_fds=True, cwd=JS_PATH)

  js_out = ''
  for js_line in js_p.stdout:
    js_out += js_line.decode().strip('\n')

  result = re.search('{ "steps": \[.+\]}', js_out)
  result = json.loads(result.group(0))
  steps = []
  for step in result['steps']:
    trace_step = {}
    trace_step['pc'] = step['pc']
    trace_step['op'] = step['op']
    trace_step['gas'] = step['gas']
    trace_step['stack'] = step['stack']
    trace_step['depth'] = step['depth']
    
    steps.append(toText(trace_step))

  return steps 

def doCpp(test_subfolder, test_name, test_dgv):
	# use string to Popen
	cpp_cmd = TESTETH
	cpp_cmd += " -t StateTestsGeneral/" + test_subfolder + " --"
	cpp_cmd += " --singletest " + test_name
	cpp_cmd += " --jsontrace '{ \"disableStorage\":true, \"disableMemory\":true }'"
	cpp_cmd += " --singlenet " + FORK_CONFIG
	#cpp_cmd += " -d 63 -g 0 -v 0"
	cpp_cmd += " -d " + str(test_dgv[0]) + " -g " + str(test_dgv[1]) + " -v " + str(test_dgv[2])
	cpp_cmd += " --testpath \"" + TESTS_PATH + "\""
	print("cpp_cmd:")
	print(cpp_cmd)
	cpp_p = subprocess.Popen(cpp_cmd, shell=True, stdout=subprocess.PIPE, close_fds=True)
	print("cpp_result:", cpp_p)

	"""
	# use list to Popen
	cpp_cmd = []
	cpp_cmd.append(TESTETH)
	cpp_cmd.append("-t")
	cpp_cmd.append("StateTestsGeneral/"+test_subfolder)
	cpp_cmd.append("--")
	cpp_cmd.append("--singletest")
	cpp_cmd.append(test_name)
	cpp_cmd.append("--jsontrace")
	# cannot get the json options to pass in correctly with cpp_cmd as an array and shell=False
	cpp_cmd.append("'{\"disableStorage\":true,\"disableMemory\":true}'")
	cpp_cmd.append("--singlenet")
	cpp_cmd.append(FORK_CONFIG)
	cpp_cmd.append("-d")
	cpp_cmd.append(str(test_dgv[0]))
	cpp_cmd.append("-g")
	cpp_cmd.append(str(test_dgv[1]))
	cpp_cmd.append("-v")
	cpp_cmd.append(str(test_dgv[2]))
	cpp_cmd.append("--testpath")
	cpp_cmd.append(CPP_PATH)
	print("cpp_cmd:")
	print(" ".join(cpp_cmd))
	cpp_p = subprocess.Popen(cpp_cmd, shell=False, stdout=subprocess.PIPE, close_fds=True)
	print("cpp_result:", cpp_p)
	"""

	cpp_out = []
	for cpp_line in cpp_p.stdout:
		cpp_out.append(cpp_line.decode())
		print(cpp_line.decode())
	
	#cpp_out = cpp_out[3:4]
	#cpp_out = cpp_out[-1]
	#print ("cpp_out lines should be 1:", len(cpp_out))
	#if len(cpp_out) < 1:
	#	cpp_steps = []
	#else:

	cpp_steps = [] # if no output
	for c_line in cpp_out:
		#print("c_line[0:1]:", c_line[0:1])
		#print("c_line[0:2]:", c_line[0:2])
		if c_line[0:2] == '[{': # detect line with json trace
			cpp_steps = json.loads(c_line)
	
	canon_steps = []
	prev_step = {}
	for c_step in cpp_steps:
		print("cpp step:", c_step)
		#if 'opName' in prev_step:
		#	if prev_step['opName'] == 'SUICIDE':
		#		prev_step = {}
		#		continue # cpp logs SUICIDE twice
		trace_step = {}
		trace_step['pc'] = c_step['pc']
		c_step['opName'] = c_step['op']
		if c_step['op'] == 'INVALID':
			continue
		if c_step['op'] not in OPCODES:
			print("got cpp step for invalid opcode:")
			print(c_step)
			continue
		trace_step['op'] = OPCODES[c_step['op']]
		c_step['gas'] = int(c_step['gas'])
		if c_step['op'] == 'STOP':
			continue
		#if c_step['op'] == "CALL":
			#c_step['gas'] += 700
			#c_step['gas'] += int(c_step['gasCost']) # on CALL steps, cpp deducts gas before logging
		trace_step['gas'] = '0x{0:01x}'.format(c_step['gas'])
		trace_step['depth'] = c_step['depth']
		trace_step['stack'] = toHexQuantities(c_step['stack'])
		prev_step = c_step
		canon_steps.append(toText(trace_step))

	return canon_steps

#DO_TEST = None

#DO_TEST = 'CALL_BoundsOOG'

DO_TEST = 'callcall_00'

#f: /Users/macbook/dev_pyethereum/metro_tests/pyethereum/fixtures/GeneralStateTests copy/stQuadraticComplexityTest/Call1MB1024Calldepth.json



SKIP_LIST = [
'POP_Bounds',
'POP_BoundsOOG',
'MLOAD_Bounds',
'Call1024PreCalls', # Call1024PreCalls does produce a consensus bug, worth fixing that trace
'createInitFailStackSizeLargerThan1024',
'createJS_ExampleContract',
'CALL_Bounds',
'mload32bitBound_Msize ',
'mload32bitBound_return2',
'Call1MB1024Calldepth ',
'shallowStackOK',
'static_CallToNameRegistratorAddressTooBigLeft',
'static_log3_MaxTopic',
'static_log4_Caller',
'static_RawCallGas',
'static_RawCallGasValueTransfer',
'static_RawCallGasValueTransferAsk',
'static_RawCallGasValueTransferMemory',
'static_RawCallGasValueTransferMemoryAsk',
'static_refund_CallA_notEnoughGasInCall',
'HighGasLimit', # geth doesn't run
'OverflowGasRequire2',
'TransactionDataCosts652',
]


START_I = 0
FILE_I = 0



#START_I = 350
#START_I = 380
#START_I = 850
#START_I = 920
#START_I = 1000
#START_I = 1080
START_I = 0

def main():
	global FILE_I
	all_files = getAllFiles()
	fail_count = 0
	pass_count = 0
	failing_files = []
	for f in all_files:
		FILE_I += 1
		if FILE_I < START_I:
			continue
		if f.find("stMemoryTest") != -1:
			continue
		if f.find("stMemoryStressTest") != -1:
			continue
		if f.find("stQuadraticComplexityTest") != -1:
			continue

		if f.find("VMTests") != -1:
			continue
		if f.find("Filler") != -1:
			continue


		with open(f) as json_data:
			general_test = json.load(json_data)
			test_name = list(general_test.keys())[0]
			if DO_TEST is not None and test_name != DO_TEST:
				continue
			if test_name in SKIP_LIST:
				print("skipping test:", test_name)
				continue
			print("f:", f)
			print("test_name:", test_name + ".")
		try:
			prestate, txs_dgv = convertGeneralTest(f)
			#txs = txs_dgv[0]
		except Exception as e:
			print("problem with test file, skipping.")
			continue

		print("prestate:", prestate)
		print("txs:", txs_dgv)
		with open(PRESTATE_TMP_FILE, 'w') as outfile:
			json.dump(prestate, outfile)
			
		with open(PRESTATE_TMP_FILE) as json_data:
			test_case = json.load(json_data)

		test_subfolder = f.split(os.sep)[-2]
		for tx_and_dgv in txs_dgv:
			tx = tx_and_dgv[0]
			tx_dgv = tx_and_dgv[1]
			print("f:", f)
			print("test_name:", test_name + ".")
			
			equivalent = True
			cpp_canon_trace = doCpp(test_subfolder, test_name, tx_dgv)
			import pdb; pdb.set_trace()
			js_canon_trace = doJs()
			#print("got cpp_canon_trace:", cpp_canon_trace)
			#canon_traces = list(itertools.izip_longest(a, b, c)) # py2
			canon_traces = list(itertools.zip_longest(js_canon_trace, cpp_canon_trace)) # py3
			print("comparing traces:")
			for steps in canon_traces:
				[js, cpp] = steps
				if js  == cpp:
					print("[*]          %s" % js)
				else:
					equivalent = False
					print("[!!]   JS:>> %s \n" % (js))
					print("[!!]  CPP:>> %s \n" % (cpp))

			if equivalent is False:
				fail_count += 1
				print("CONSENSUS BUG!!!\a")
				failing_files.append(test_name)
			else:
				pass_count += 1
				print("equivalent.")
			print("f/p/t:", fail_count, pass_count, (fail_count + pass_count))
			print("failures:", failing_files)

	print("fail_count:", fail_count)
	print("pass_count:", pass_count)
	print("total:", fail_count + pass_count)




"""
## could not get redirect_stdout to work
## need to get this working for python-afl fuzzer
def runStateTest(test_case):
    print("running stateTest")
    _state = init_state(test_case['env'], test_case['pre'])
    print("inited state:", _state.to_dict())
    f = io.StringIO()
    with redirect_stdout(f):
        computed = compute_state_test_unit(_state, test_case["transaction"], config_spurious)
    f.seek(0)
    py_out = f.read()
    print("py_out:", py_out)
    #computed = compute_state_test_unit(_state, test_case["transaction"], config_spurious)
    print("computed:", computed)
"""


if __name__ == '__main__':
	print("main.")
	#import afl
	#afl.start()
	main()

sys.argv
