#! /usr/bin/env python
# encoding: utf-8

# Copyright (c) 2015-2010 Stanford Research Systems

# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnshished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
# THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
# FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
# DEALINGS IN THE SOFTWARE.


""" Example python script to setup and get data capture from an SR865.

        Tested with python 2.7
        Typical installation will require vxi11 and docopt installation in the usually way.

        python cap860.py -h        to see the list of options
        Default options can be changed by editing the useStr (below).
        You will certainly need to change the IP address to match your SR865 and for compatability with your network.

"""
import math
from struct import unpack_from
import signal
import sys
import time


# you may need to install these python modules
try:
    import vxi11            # required
except ImportError:
    print 'required python vxi11 library not found. Please install vxi11'

try:
    import docopt           # handy command line parser. useStr (below) defines the syntax and documents it at the same time.
except ImportError:
    print 'python docopt library not found. Please install docopt or remove the docopt code from test() and main'


useStr = """
 --Capture Data on an SR865 and save it to a file--
 Usage:
  cap860  [--address=<A>] [--count=<C>] [--debug] [--file=<F>] [--mode=<M>] [--silent] [--vars=<V>] [--wait=<W>]
  cap860 -h | --help

 Options:
  -a --address <A>     IP address of SR865 [default: 172.25.98.253]
  -c --count <C>       number of data points to capture [default: 500]
  -d --debug           Print lot's of stuff
  -f --file <F>        Name for file output. No file output without a file name.
  -h --help            Show this screen
  -m --mode <M>        Trigger mode [default: IMM]  TRIG or SAMP are also allowed
  -s --silent          Refrain from printing running capture count and data until complete
  -w --wait <W>        Seconds to wait for a point before timeout [default: 5]
  -v --vars <V>        Lock-in variables to stream [default: X]    XY, RT, or XYRT are also allowed
    """


def show_status(l='',r=''):
    """ Simple text status line that overwrites itself to prevent scrolling.
    """
    print ' %-30s %48s\r'%(l[:30],r[:48]),


# global that gets assigned to the vxi11 object to allow SIGINT to cleanup properly
vx      = None


def cleanup():
    """ Stop the stream and close the socket and vxi11.
    """
    # global vx
    print "\n cleaning up...",
    vx.close()
    print 'connections closed\n'


def open_interfaces(ipadd):
    """ open a vxi11 instrument and assign it to the global vx
    """
    global vx
    print'opening VXI-11 at %s ...' % ipadd,
    vx = vxi11.Instrument(ipadd)
    print 'done'



def dut_config(vx, sStrChans, iWaitCount):
    """ Setup the SR865 for streaming. Return the total expected sample count
    """
    vx.write('CAPTURECFG %s'%sStrChans)    # the vars to captures
    iCapLenK = math.ceil(len(sStrChans) * iWaitCount / 256.0)
    vx.write('CAPTURELEN %d'%iCapLenK)   # in kB. dut rounds odd numbers up to next even
    # print 'CAPTURELEN %d'%iCapLenK       # in kB. dut rounds odd number up
    fRateMax = float(vx.ask('CAPTURERATEMAX?'))      # filters determine the max data rate
    return fRateMax


def capture_data(vx, s_mode, s_channels, i_wait_count, t_timeout, b_show_status):
    t_start = time.clock()
    vx.write('CAPTURESTART ONE, %s'%s_mode)
    i_bytes_captured = 0
    i_last_cap_byte = 0
    t_last = t_start
    while i_bytes_captured < (i_wait_count * 4 * len(s_channels)):
        i_bytes_captured = int(vx.ask('CAPTUREBYTES?'))
        if b_show_status:
            show_status('dut has captured %4d of %4d samples'%(i_bytes_captured / (4 * len(s_channels)), i_wait_count))
        if (i_bytes_captured - i_last_cap_byte) == 0:
            if (time.clock() - t_last) > t_timeout:
                print '\n\n**** CAPTURE TIMEOUT! ****'
                if not i_bytes_captured:
                    print '**** NO DATA CAPTURED - missing trigger? ****\n'
                    sys.exit(-1)
                break
        else:
            t_last = time.clock()
        i_last_cap_byte = i_bytes_captured
    t_end = time.clock()
    vx.write('CAPTURESTOP')
    print 'capture took %.3f seconds. Retrieving data...'%(t_end-t_start)
    return i_bytes_captured


def retrieve_data(vx, i_bytes_captured, i_wait_count, s_channels):
    """ Use the binary transfer command over vx interface to retrieve the capture buffer.
        maximum block count for CAPTUREGET? is 64 so loop over blocks as needed to
        get all the desired data.
        Note: I don't actually look at the data byte count in the response header.
            Instead, I use the length of the binary buffer returned to calculate
            the number of floats to convert.
    """
    i_bytes_remaining = min(i_bytes_captured, i_wait_count * 4 * len(s_channels))
    i_block_offset = 0
    f_data = []
    i_retries = 0
    while i_bytes_remaining > 0:
        i_block_cnt = min(64, int(math.ceil(i_bytes_remaining / 1024.0)))
        vx.write('CAPTUREGET? %d, %d'%(i_block_offset, i_block_cnt))
        buf = vx.read_raw()         # read whatever dut sends
        if not len(buf):
            print 'empty response from dut for block %d'%i_block_offset
            i_retries += 1
            if i_retries > 5:
                print '\n\n**** TOO MANY RETRIES ATTEMPTING TO GET DATA! ****'
                if not i_block_offset:
                    print '**** NO DATA RETUNED ****\n'
                    sys.exit(-1)

        # binary block CAPTUREGET returns #nccccxxxxxxx... with little-endian float x bytes see manual page 139
        # if b_show_debug:
        if False:
            print ' '.join(['%02X'%ord(x) for x in buf[:6]])
            print str_blocks_hex(buf[6:262])

        raw_data = buf[2 + int(buf[1]):]
        i_bytes_to_convert = min(i_bytes_remaining, len(raw_data))
        f_block_data = list(unpack_from('<%df'%(i_bytes_to_convert/4), raw_data))      # convert to floats
        # if b_show_debug:
        if False:
            print len(f_block_data), 'floats received'
            print str_blocks_float(f_block_data)
        f_data += f_block_data
        i_block_offset += i_block_cnt
        i_bytes_remaining -= i_block_cnt * 1024
    return f_data


def write_to_file(file_name, s_channels, f_data, open_mode = 'a'):
    """ Save ASCII data to a comma separated file. We could also have used the csv python module...
    """
    if f_data:
        show_status('writing %s ...'%file_name)
        with open(file_name, open_mode) as fl:
            s_fmt = '%+12.6e,'*len(s_channels)
            fl.write(''.join(['%s,'%str.upper(v) for v in s_channels])+'\n')
            for i in range(0, len(f_data)/len(s_channels), len(s_channels)):
                x = f_data[i:i+len(s_channels)]
                fl.write(s_fmt%tuple(x)+'\n')
            show_status('%s written'%file_name)
    else:
        show_status('no data! File not writtten!')


def str_blocks_hex(buf):
    """ Handy formatting for looking at the binary data. Returns a string with spaces
        and line-feeds to make it easy to find locations.
    """
    return ' '.join(['%s%s%s%s%02X'%('' if i==0 or i%32 != 0 else '\n', # add a line-feed every 8 blocks
                                     '' if i==0 or i%128 != 0 else '\n',# add an extra line-feed every 4 lines
                                     '' if i%4 != 0 else ' ',           # add an extra space every 4 values
                                     '' if i%16 != 0 else ' ',          # add another extra space every block of 4
                                     ord(x)) for i, x in enumerate(buf)])

def str_blocks_float(buf):
    """ Handy formatting for looking at the float data. Returns a string with spaces
        and line-feeds to make it easy to find locations.
    """
    return ' '.join(['%s%s%s%12.4e'%('' if i==0 or i%8 != 0 else '\n',  # add a line-feed every 8 values
                                     '' if i==0 or i%32 != 0 else '\n', # add an extra line-feed every 4 lines
                                     '' if i%4 != 0 else ' ',           # add an extra space every 4 values
                                     x) for i, x in enumerate(buf)])


# socket seems to catch the KeyboardInterrupt exception if I don't grab it explicitly here
def interrupt_handler(signum, frame):
    cleanup()
    sys.exit(-2)      # Terminate process here as catching the signal removes the close process behaviour of Ctrl-C


signal.signal(signal.SIGINT, interrupt_handler)



def enforce_choice( key, d, allowed):
    """ Some CLI args have a specific list of allowed values.
        Make sure we got one of the allowed values and return it upper case.
    """
    if not d[key].upper() in allowed:
        print '%s option was %s. Must be one of'%(key, d[key]), ' '.join(allowed)
        sys.exit(-1)
    return d[key].upper()



# the main program -----------------------------------------------
def test(opts):
    # global vx

    # group the docopt stuff to make it easier to remove, if desired
    dut_add  = opts['--address']                # IP address of the SR86x
    i_wait_count = int(opts['--count'])         # how many points to capture
    f_name = opts['--file']                     # file to write, if file name provided
    b_show_status = not opts['--silent']
    b_show_debug = opts['--debug']
    t_timeout = float(opts['--wait'])           # give up if dut takes more than 'wait' seconds between points

    s_channels = enforce_choice('--vars', opts, ['X','XY','RT','XYRT'])
    s_mode = enforce_choice('--mode', opts, ['IMM','TRIG','SAMP',])

    # --------------- setup the capture ---------------------------
    open_interfaces(dut_add)                    # sets the vx global to our comm object
    f_rate_max = dut_config(vx, s_channels, i_wait_count)
    vx.write('CAPTURESTOP')                     # stop any current capture

    show_status('waiting for capture (at least %.1f seconds)...'%(i_wait_count/f_rate_max))
    if 'IMM' not in s_mode:
        show_status( 'FYI: apply trigger to BNC')

    # --------------- capture the data and retieve it from the dut ------------
    i_bytes_captured = capture_data(vx, s_mode, s_channels, i_wait_count, t_timeout, b_show_status)
    f_data = retrieve_data(vx, i_bytes_captured, i_wait_count, s_channels)

    # ------------- display or write the data to a file -----------------------
    if b_show_debug and i_bytes_captured:
        print 'first 16:'
        print str_blocks_float(f_data[:16])
        print '   ...\nlast 16:'
        print str_blocks_float(f_data[-16:])

    if f_name is not None:
        write_to_file(f_name, s_channels, f_data, 'w')
    cleanup()


if __name__ == '__main__':
    opts = docopt.docopt(useStr, version='0.0.2')
    test(opts)

