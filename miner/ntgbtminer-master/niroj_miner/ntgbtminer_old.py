import urllib2
import base64
import json
import hashlib
import struct
import time
import midstate
import util
import sha256_download
import serial_comm
import random
import midstate_little
from config import PORT_ADDRESS, DEBUG_LOCAL_DATA, PUBLIC_KEY, COINBASE_MSG, SUBMIT_DATA, TARGET_REDUCE


serial = None
DEBUG_STRING = "MINER_MAIN"
################################################################################
# Transaction Coinbase and Hashing Functions
################################################################################

# Create a coinbase transaction
#
# Arguments:
#       coinbase_script:    (hex string) arbitrary script
#       address:            (base58 string) bitcoin address
#       value:              (unsigned int) value
#
# Returns transaction data in ASCII Hex


def tx_make_coinbase(coinbase_script, address, value):
    # See https://en.bitcoin.it/wiki/Transaction

    # Create a pubkey script
    # OP_DUP OP_HASH160 <len to push> <pubkey> OP_EQUALVERIFY OP_CHECKSIG
    pubkey_script = "76" + "a9" + "14" + util.bitcoinaddress2hash160(address) + "88" + "ac"

    tx = ""
    # version
    tx += "01000000"
    # in-counter
    tx += "01"
    # input[0] prev hash
    tx += "0"*64
    # input[0] prev seqnum
    tx += "ffffffff"
    # input[0] script len
    tx += util.int2varinthex(len(coinbase_script)/2)
    # input[0] script
    tx += coinbase_script
    # input[0] seqnum
    tx += "ffffffff"
    # out-counter
    tx += "01"
    # output[0] value (little endian)
    tx += util.int2lehex(value, 8)
    # output[0] script len
    tx += util.int2varinthex(len(pubkey_script)/2)
    # output[0] script
    tx += pubkey_script
    # lock-time
    tx += "00000000"

    return tx

# Compute the SHA256 Double Hash of a transaction
#
# Arguments:
#       tx:    (hex string) ASCII Hex transaction data
#
# Returns a SHA256 double hash in big endian ASCII Hex
def tx_compute_hash(tx):
    h1 = hashlib.sha256(util.hex2bin(tx)).digest()
    h2 = hashlib.sha256(h1).digest()
    return util.bin2hex(h2[::-1])

# Compute the Merkle Root of a list of transaction hashes
#
# Arguments:
#       tx_hashes:    (list) ASCII Hex transaction hashes
#
# Returns a SHA256 double hash in big endian ASCII Hex
def tx_compute_merkle_root(tx_hashes):
    # Convert each hash into a binary string
    for i in range(len(tx_hashes)):
        # Reverse the hash from big endian to little endian
        tx_hashes[i] = util.hex2bin(tx_hashes[i])[::-1]

    # Iteratively compute the merkle root hash
    while len(tx_hashes) > 1:
        # Duplicate last hash if the list is odd
        if len(tx_hashes) % 2 != 0:
            tx_hashes.append(tx_hashes[-1][:])

        tx_hashes_new = []
        for i in range(len(tx_hashes)/2):
            # Concatenate the next two
            concat = tx_hashes.pop(0) + tx_hashes.pop(0)
            # Hash them
            concat_hash = hashlib.sha256(hashlib.sha256(concat).digest()).digest()
            # Add them to our working list
            tx_hashes_new.append(concat_hash)
        tx_hashes = tx_hashes_new

    # Format the root in big endian ascii hex
    return util.bin2hex(tx_hashes[0][::-1])

################################################################################
# Block Preparation Functions
################################################################################

# Form the block header
#
# Arguments:
#       block:      (dict) block data in dictionary
#
# Returns a binary string
def block_form_header(block):
    header = ""

    # Version
    header += struct.pack("<L", block['version'])
    # Previous Block Hash
    header += util.hex2bin(block['previousblockhash'])[::-1]
    # Merkle Root Hash
    header += util.hex2bin(block['merkleroot'])[::-1]
    # Time
    header += struct.pack("<L", block['curtime'])
    # Target Bits
    header += util.hex2bin(block['bits'])[::-1]
    # Nonce
    header += struct.pack("<L", block['nonce'])
    return header

# Compute the Raw SHA256 Double Hash of a block header
#
# Arguments:
#       header:    (string) binary block header
#
# Returns a SHA256 double hash in big endian binary
def block_compute_raw_hash(header):
    return hashlib.sha256(hashlib.sha256(header).digest()).digest()[::-1]

# Convert block bits to target
#
# Arguments:
#       bits:       (string) compressed target in ASCII Hex
#
# Returns a target in big endian binary
def block_bits2target(bits):
    # Bits: 1b0404cb
    # 1b -> left shift of (0x1b - 3) bytes
    # 0404cb -> value
    shift = ord(util.hex2bin(bits[0:2])[0]) - 3
    value = util.hex2bin(bits[2:])

    # Shift value to the left by shift (big endian)
    target = value + "\x00"*shift
    # Add leading zeros (big endian)
    target = "\x00"*(32-len(target)) + target

    return target

# Check if a block header hash meets the target hash
#
# Arguments:
#       block_hash: (string) block hash in big endian binary
#       target:     (string) target in big endian binary
#
# Returns true if header_hash meets target, false if it does not.
#Both block_hash and target_hash are in big endian format
def block_check_target(block_hash, target_hash):
    # Header hash must be strictly less than or equal to target hash
    bHashLower = block_hash.lower()
    tHashLower = target_hash.lower()
    for i in range(len(bHashLower)):
        if ord(bHashLower[i]) == ord(tHashLower[i]):
            continue
        elif ord(bHashLower[i]) < ord(tHashLower[i]):
            return True
        else:
            return False

# Format a solved block into the ASCII Hex submit format
#
# Arguments:
#       block:      (dict) block
#
# Returns block in ASCII Hex submit format
def block_make_submit(block):
    subm = ""

    # Block header
    subm += util.bin2hex(block_form_header(block))
    # Number of transactions as a varint
    subm += util.int2varinthex(len(block['transactions']))
    # Concatenated transactions data
    for tx in block['transactions']:
        subm += tx['data']

    return subm

################################################################################
# Mining Loop
################################################################################

def fpga_miner(block_template, coinbase_message, extranonce_start, address, timeout=False, debugnonce_start=False, debug=False):
    # Add an empty coinbase transaction to the block template
    if debug:
        print ""
        print "Algorithm start:"
        print ""
    coinbase_tx = {}
    block_template['transactions'].insert(0, coinbase_tx)
    # Add a nonce initialized to zero to the block template
    block_template['nonce'] = 0

    # Compute the target hash
    target_hash = block_bits2target(block_template['bits'])
    if debug == True:
        print block_template['bits']
        print "target_hash", util.bin2hex(target_hash)

    # Initialize our running average of hashes per second
    hps_list = []

    # Loop through the extranonce
    extranonce = extranonce_start
    coinbase_script = coinbase_message + util.int2lehex(extranonce, 4)
    coinbase_tx['data'] = tx_make_coinbase(coinbase_script, address, block_template['coinbasevalue'])
    coinbase_tx['hash'] = tx_compute_hash(coinbase_tx['data'])
    
    # Recompute the merkle root
    tx_hashes = [tx['hash'] for tx in block_template['transactions']]
    block_template['merkleroot'] = tx_compute_merkle_root(tx_hashes)

    # Reform the block header
    block_header = block_form_header(block_template)
    #Block header should be in big endian#
    #local_hash_little(block_header)
    #local_hash_big(block_header)
    my_data = midstate.calculateMidstate(block_header[0:64])

    midstatesw = util.bin2hex(my_data)
    targetsw = util.bin2hex(target_hash)
    secondhalf = util.bin2hex(block_header[64:76])
    if True:
        targetsw = TARGET_REDUCE + targetsw[8:len(targetsw)]
        target_hash = util.hex2bin(targetsw)
    if debug == True:
        '''
        This is used to checking the hash generation through the local information!!!
        '''
        new_data = util.hex2bin('00000000800000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000280')
        second_head = block_header[64:76] + new_data
        data_temp = midstate.calculateMidstate( second_head, my_data, 64 )
        print "fpga_mine-> block_header:", util.bin2hex(block_header)
        print "midstate_calc:[1]", util.bin2hex(data_temp)
        print "fpga_mine->header_hash first round[1]", hashlib.sha256(block_header).hexdigest()
        print "fpga_mine-> header_hash:[2]", hashlib.sha256(data_temp).hexdigest()
        print "fpga_mine->header_hash two round[2]", hashlib.sha256(hashlib.sha256(block_header).digest()).hexdigest()
        return None, 0

    time_stamp = time.clock()
    serial.write_data(secondhalf, midstatesw, targetsw)
    time_elapsed = time.clock() - time_stamp
    print "Time Elapsed( FPGA - MINER ):", time_elapsed
    time_stamp = time.clock()
    double_hash( block_header[:76], target_hash)
    time_elapsed = time.clock() - time_stamp
    print "Time Elapsed( PC - MINER ):", time_elapsed
    if SUBMIT_DATA:
        block_submission(block_template, block_header, ser.get_nonce(), target_hash)
    return

def block_submission(block_template, block_header, nonce, target_hash):
    nonce_str = chr(nonce & 0xff) + chr((nonce >> 8) & 0xff) + chr((nonce >> 16) & 0xff) + chr((nonce >> 24) & 0xff)
    block_hash = block_compute_raw_hash(block_header+nonce_str)
    if util.block_check_target(util.bin2hex(block_hash), target_hash):
        #Submit the data again
        block_template['nonce'] = nonce
        block_template['hash'] = bin2hex(block_hash)
        print "Solved a block! Block hash:", mined_block['hash']
        submission = block_make_submit(mined_block)
        print "Submitting:", submission, "\n"
        rpc_submitblock(submission)
    return

def local_sha256( secondhalf, midstate_data, target_hash ):
    #TODO: make sure the nonce is started with 0x00000fff so that it can be started properly
    print "Local sha256"
    new_target = serial.get_target()
    print "Target received:", new_target
    nonce = 0
    while nonce <= 0xffffffff:
        nonce_str = chr(nonce & 0xff) + chr((nonce >> 8) & 0xff) + chr((nonce >> 16) & 0xff) + chr((nonce >> 24) & 0xff)
        new_data = nonce_str + util.hex2bin('800000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000280')
        second_head = secondhalf + new_data
        temp_hash = midstate.calculateMidstate( second_head, midstate_data, 64 )
        block_hash = hashlib.sha256(temp_hash).digest()
        if util.block_check_target(util.bin2hex(block_hash), new_target):
            print 'nonce_str: ', nonce_str
            print 'Target hash found for nonce = ', nonce
            print 'block_hash = ' , util.bin2hex( block_hash )
            print 'target_hash = ' , new_target
            return None, 0

        nonce += 1

    return None, 0

def local_sha256_with_nonce( secondhalf, midstate_data, target_hash ):
    print 'SHA with nonce'
    new_target = serial.get_target()
    nonce_str = util.hex2bin( serial.get_nonce() )
    new_data = nonce_str + util.hex2bin('800000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000280')
    second_head = secondhalf + new_data
    temp_hash = midstate.calculateMidstate( second_head, midstate_data, 64 )
    block_hash = hashlib.sha256(temp_hash).digest()
    print "target:", new_target
    print util.bin2hex( block_hash )

def double_hash(block_header, target_hash):
    print 'Double hash'
    nonce = 0
    while nonce <= 0xffffffff:
        # Update the block header with the new 32-bit nonce
        block_header = block_header[0:76] + chr(nonce & 0xff) + chr((nonce >> 8) & 0xff) + chr((nonce >> 16) & 0xff) + chr((nonce >> 24) & 0xff)
        #block_header = block_header[0:76] + chr(nonce >> 24 & 0xff) + chr((nonce >> 16) & 0xff) + chr((nonce >> 8) & 0xff) + chr(nonce  & 0xff)
        # Recompute the block hash
        block_hash = block_compute_raw_hash(block_header)
        if util.block_check_target(block_hash, target_hash):
            print "nonce: ", nonce
            print util.bin2hex(block_hash)
            break
        nonce += 1


def local_hash_little(block_header):
    print len(block_header[0:64])
    new_block = util.convetToLittleEndian(block_header[0:64])
    print "Block header:", util.bin2hex(block_header[:64])
    print "New Block   :", util.bin2hex(new_block)       

    my_data = midstate_little.calculateMidstate(new_block[0:64])
    new_data = util.hex2bin('00000000800000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000280')
    second_head = block_header[64:76] + new_data
    new_block = util.convetToLittleEndian(second_head)
    new_temp = midstate_little.calculateMidstate( new_block, my_data, 64 )
    print "Loop2:  ", util.bin2hex(second_head)
    print "Little: ", util.bin2hex(new_block)
    print "New Temp(hash)1", util.bin2hex(new_temp)
    print "Level 1 hash  1", hashlib.sha256(block_header).hexdigest()
    new_data = util.hex2bin('800000000000000000000000000000000000000000000000') + util.hex2bin('0000000000000100')
    new_block = new_temp + util.convetToLittleEndian(new_data)
    hash_calc = midstate_little.calculateMidstate( new_block )
    print "New Temp(hash)2", util.bin2hex(hash_calc)
    print "Level 1 hash  2", hashlib.sha256(hashlib.sha256(block_header).digest()).hexdigest()
    print util.bin2hex(hash_calc)

def local_hash_big(block_header):
    print "Lib Hash:", hashlib.sha256(hashlib.sha256(block_header).digest()).hexdigest()
    my_data = midstate.calculateMidstate(block_header[0:64])
    new_data = util.hex2bin('00000000800000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000280')
    second_head = block_header[64:76] + new_data
    temp_hash = midstate.calculateMidstate( second_head, my_data, 64 )
    print "Level 1: ", util.bin2hex(hashlib.sha256(temp_hash).digest())
    print "Just Level 1:", util.bin2hex(temp_hash)
    new_data = temp_hash + util.hex2bin('800000000000000000000000000000000000000000000000') + util.hex2bin('0000000000000100')
    hash_calc = midstate.calculateMidstate( new_data )
    print util.bin2hex(hash_calc)



def fpga_miner_with_debug_data():
    block_header_str = "000000202fa8edaec2e28b3b6a9f81b2f4dc572e3b76ba87ffd934fe8001000000000000821e03b6e528af7cdeea67e2c59373a4d6b351e036acf6a3f23712df3f08c2f5d0a88857e28a011a"
    target_hash_str = "000000000000018ae20000000000000000000000000000000000000000000000"
    block_header = util.hex2bin(block_header_str)
    target_hash = util.hex2bin(target_hash_str)
    my_data = midstate.calculateMidstate(block_header[0:64])
    midstatesw = util.bin2hex(my_data)
    targetsw = util.bin2hex(target_hash)
    secondhalf = util.bin2hex(block_header[64:76])

    if True:
        targetsw = TARGET_REDUCE + targetsw[8:len(targetsw)]
        target_hash = util.hex2bin(targetsw)
    time_stamp = time.clock()
    serial.write_data(secondhalf, midstatesw, targetsw)
    time_elapsed = time.clock() - time_stamp
    print "Time Elapsed( FPGA - MINER ):", time_elapsed
    time_stamp = time.clock()
    double_hash( block_header[:76], target_hash)
    time_elapsed = time.clock() - time_stamp
    print "Time Elapsed( PC - MINER ):", time_elapsed


def standalone_miner(coinbase_message, address):
    print "Mining new block template..."
    if DEBUG_LOCAL_DATA:
        fpga_miner_with_debug_data()
    else:
        if SUBMIT_DATA:
            while True:
                block_template1 = util.rpc_getblocktemplate()
                fpga_miner(block_template1, coinbase_message, 0, address, timeout=60, debug=False)
        else:
            block_template1 = util.rpc_getblocktemplate()
            fpga_miner(block_template1, coinbase_message, 0, address, timeout=60, debug=False)



if __name__ == "__main__":
    serial = serial_comm.MySerial(serial_port=PORT_ADDRESS, debug=False)
    standalone_miner(util.bin2hex(COINBASE_MSG), PUBLIC_KEY)
