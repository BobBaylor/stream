#! /usr/bin/env python
# encoding: utf-8

# Copyright (c) 2015-2017 Stanford Research Systems

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


""" Example python script to capture streaming data from an SR865.

        Tested with python 2.7
        Typical installation will require vxi11 and docopt installation in the usually way.

  ****  Your host computer firewall MUST allow incoming UDP on the streaming port !!! ****
        See your IT person if you need help with this. Streaming cannot work without the open port.

        python stream.py -h        to see the list of options
        Default options can be changed by editing the useStr (below).
        You will certainly need to change the IP address to match your SR865 and
        for compatability with your network.

"""
import math
import socket
from struct import unpack_from
import signal
import sys
import time
import threading
import Queue

# you may need to install these python modules
try:
    import vxi11            # required
except ImportError:
    print 'required python vxi11 library not found. Please install vxi11'

try:
    import docopt           # handy command line parser.
except ImportError:
    print 'python docopt library not found. Please install docopt'


USE_STR = """
 --Stream Data from an SR865 to a file--
 Usage:
  stream  [--address=<A>] [--length=<L>] [--port=<P>] [--duration=<D>] [--vars=<V>] [--rate=<R>] [--silent] [--thread] [--file=<F>] [--ints]
  stream -h | --help

 Options:
  -a --address <A>     IP address of SR865 [default: 172.25.98.253]
  -d --duration <D>    How long to transfer in seconds [default: 10]
  -f --file <F>        Name for file output. No file output without a file name.
  -h --help            Show this screen
  -i --ints            Data in 16-bit ints instead of 32-bit floats
  -l --length <L>      Packet length enum (0 to 3) [default: 0]
  -p --port <P>        UDP Port [default: 1865]
  -r --rate <R>        Sample rate per second. Actual will be less and depends on filter settings [default: 1e5]
  -s --silent          Refrain from printing packet count and data until complete
  -t --thread          Decouple output from ethernet stream using threads
  -v --vars <V>        Lock-in variables to stream [default: X]    XY, RT, or XYRT are also allowed
    """

def show_status(left_text='', right_text=''):
    """ Simple text status line that overwrites itself to prevent scrolling.
    """
    print ' %-30s %48s\r'%(left_text[:30], right_text[:48]),

# globals get assigned the udp and vxi11 objects to allow SIGINT to cleanup properly
# pylint wants me to name these in all caps, as if they are constants. They're not.
the_udp_socket = None       #pylint: disable=global-statement, invalid-name
the_vx_ifc = None           #pylint: disable=global-statement, invalid-name

def cleanup_ifcs():
    """ Stop the stream and close the socket and vxi11.
    """
    # global the_udp_socket
    # global the_vx_ifc
    print "\n cleaning up...",
    the_vx_ifc.write('STREAM OFF')
    the_vx_ifc.close()
    the_udp_socket.close()
    print 'connections closed\n'



def open_interfaces(ipadd, port):
    """ open a UDP socket and a vxi11 instrument and assign them to the globals
    """
    global the_udp_socket   #pylint: disable=global-statement, invalid-name
    global the_vx_ifc       #pylint: disable=global-statement, invalid-name
    print'\nopening incoming UDP Socket at %d ...' % port,
    the_udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    the_udp_socket.bind(('', port))      # listen to anything arriving on this port from anyone
    print 'done'
    print'opening VXI-11 at %s ...' % ipadd,
    the_vx_ifc = vxi11.Instrument(ipadd)
    the_vx_ifc.write('STREAMPORT %d'%port)
    print 'done'




def dut_config(vx_ifc, s_channels, idx_pkt_len, f_rate_req, b_integers):
    """ Setup the SR865 for streaming. Return the rate (samples/sec)
    """
    vx_ifc.write('STREAM OFF')                          # turn off streaming while we set it up
    vx_ifc.write('STREAMCH %s'%s_channels)
    if b_integers:
        vx_ifc.write('STREAMFMT 1')                 # 16 bit int
    else:
        vx_ifc.write('STREAMFMT 0')                 # 32 bit float
    vx_ifc.write('STREAMOPTION 2')      # use big-endian (~1) and data integrity checking (2)
    vx_ifc.write('STREAMPCKT %d'%idx_pkt_len)
    f_rate_max = float(vx_ifc.ask('STREAMRATEMAX?'))      # filters determine the max data rate

    # calculate a decimation to stay under f_rate_req
    i_decimate = int(math.ceil(math.log(f_rate_max/f_rate_req, 2.0)))
    if i_decimate < 0:
        i_decimate = 0
    if i_decimate > 20:
        i_decimate = 20

    f_rate = f_rate_max/(2.0**i_decimate)
    print'Max rate is %.3f kS/S.'%(f_rate_max*1e-3)
    print'Decimating by 2^%d down to %.3f kS/S'%(i_decimate, f_rate*1e-3)
    vx_ifc.write('STREAMRATE %d'%i_decimate)     # bring the rate under our target rate
    return f_rate


def write_to_file(f_name, s_channels, lst_stream):
    """ Save data to a comma separated file. We could also use the csv python module...
        s_channels is "X" or "XY", etc indicating how many values in a lst_sample
        lst_stream[][] is a list of sample lists
    """
    show_status('writing %s ...'%f_name)
    with open(f_name, 'w') as f_ptr:
        f_ptr.write(''.join(['%s,'%str.upper(v) for v in s_channels])+'\n')
        if isinstance(lst_stream[0][0], float):
            s_val_fmt = '%+12.6e,'*len(s_channels)
        else:
            s_val_fmt = '%+d,'*len(s_channels)
        for lst_sample in lst_stream:
            for i in range(0, len(lst_sample), len(s_channels)):
                smpl = lst_sample[i:i+len(s_channels)]
                f_ptr.write(s_val_fmt%tuple(smpl)+'\n')
    show_status('%s written'%f_name)



# socket seems to catch the KeyboardInterrupt exception if I don't grab it explicitly here
def interrupt_handler(signum, frame):  #pylint: disable=unused-argument
    """ call my cleanup_ifcs when something bad happens
    """
    cleanup_ifcs()
    #  catching the signal removes the close process behaviour of Ctrl-C
    sys.exit(-2)      # so Terminate process here


signal.signal(signal.SIGINT, interrupt_handler)


# thread functions ----------------------------------------------
def fill_queue(sock_udp, q_data, count_packets, bytes_per_packet):
    """ Pump packets from the socket (SR865) to the python dataQueue
    """
    for _ in range(count_packets):
        buf, _ = sock_udp.recvfrom(bytes_per_packet)
        q_data.put(buf)
    cleanup_ifcs()


def process_packet(buf, fmt_unpk, prev_pkt_cntr):
    """ Unpack the header and data froma packet, checking for dropped packets.
        return the data, the header, the number of packets missed, and the current packet number.
        Only the packet counter is checked - other, possibly important information in the header
        (such as overload, unlock status, data type, streamed variables, and sample rate)
        are ignored.
    """
    # convert to floats or ints after skipping 4 bytes of header
    vals = list(unpack_from(fmt_unpk, buf, 4))
    head = unpack_from('>I', buf)[0]            # convert the header to an 32 bit int
    cntr = head & 0xff                         # extract the packet counter from the header
    # check for missed packets
    # if this isn't the 1st and the difference isn't 1 then
    if prev_pkt_cntr is not None and ((prev_pkt_cntr+1)&0xff) != cntr:
        n_dropped = cntr - prev_pkt_cntr                    # calculate how many we missed
        if n_dropped < 0:
            n_dropped += 0xff
    else:
        n_dropped = 0
    return vals, head, n_dropped, cntr


def empty_queue(q_data, q_drop, count_packets, bytes_per_packet, fmt_unpk, s_prt_fmt, s_channels, fname, bshow_status): #pylint: disable=too-many-arguments, too-many-locals, line-too-long
    """ myThreads[1] calls this to pull data out of the dataQueue.
        When all the packets have been processed:
            writes to a file (optional)
            displays the dropped packet stats
            writes the drop list (maybe empty) to q_drop.
    """
    prev_pkt_cntr = None                         # init the packet counter
    lst_dropped = []                            # make a list of any missing packets
    count_dropped = 0
    lst_stream = []
    count_vars = len(s_channels)
    for i in range(count_packets):
        buf = q_data.get()
        vals, _, n_dropped, prev_pkt_cntr = process_packet(buf, fmt_unpk, prev_pkt_cntr)
        lst_stream += [vals]
        if n_dropped:
            lst_dropped += [(n_dropped, i)]
        count_dropped += n_dropped
        if bshow_status:
            show_status('dropped %4d of %d'%(count_dropped, i+1), s_prt_fmt%tuple(lst_stream[-1][-count_vars:]))   #pylint: disable=line-too-long

    if fname is not None:
        write_to_file(fname, s_channels, lst_stream)

    show_results(count_dropped, count_packets, lst_dropped, count_packets*bytes_per_packet/(4*count_vars))    #pylint: disable=line-too-long
    q_drop.put(lst_dropped)    # signal to main thread that we finished the post-processing



def show_results(count_dropped, count_packets, lst_dropped, count_samples):
    """ print indicating OK, or some dropped packets"""
    if count_dropped:
        print '\nFAIL: Dropped %d out of %d packets in %d gaps:'%(count_dropped, count_packets, len(lst_dropped)),   #pylint: disable=line-too-long
        print ''.join('%d at %d, '%(x[0], x[1]) for x in lst_dropped[:5])
    else:
        print '\npass: No packets dropped out of %d. %d samples captured.'%(count_packets, count_samples)   #pylint: disable=line-too-long



# the main program -----------------------------------------------
def test(opts):     #pylint: disable=too-many-locals, too-many-statements
    """ example main()
    """
    # global the_udp_socket
    # global the_vx_ifc

    # group the docopt stuff to make it easier to remove, if desired
    dut_add = opts['--address']               # IP address and streaming port of the SR865
    dut_port = int(opts['--port'])
    # sample rate that host wants.
    # Actual rate will be below this and depends on filter settings
    f_rate_req = float(opts['--rate'])
    # select the packet size: 0 to 3 select 1024..128 byte packets
    idx_pkt_len = int(opts['--length'])
    duration_stream = float(opts['--duration'])     # in seconds
    bshow_status = not opts['--silent']
    fname = opts['--file']
    s_channels = str(opts['--vars'])           # what to stream. X, XY, RT, or XYRT allowed
    lst_vars_allowed = ['X', 'XY', 'RT', 'XYRT']
    b_integers = opts['--ints']
    b_use_threads = opts['--thread']

    if s_channels.upper() not in lst_vars_allowed:
        print 'bad --vars option (%s). Must be one of'%s_channels.upper(), ', '.join(lst_vars_allowed)   #pylint: disable=line-too-long
        sys.exit(-1)

    open_interfaces(dut_add, dut_port)
    f_total_samples = duration_stream * dut_config(the_vx_ifc, s_channels, idx_pkt_len, f_rate_req, b_integers)   #pylint: disable=line-too-long
    # translate the packet size enumeration into an actual byte count
    bytes_per_pkt = [1024, 512, 256, 128][idx_pkt_len]
    if b_integers:
        fmt_unpk = '>%dh'%(bytes_per_pkt/2)            # create an unpacking format string.
        fmt_live_printing = '%12d'*len(s_channels)        # create status format string.
    else:
        fmt_unpk = '>%df'%(bytes_per_pkt/4)
        fmt_live_printing = '%12.6f'*len(s_channels)

    total_packets = int(math.ceil(f_total_samples*4*len(s_channels)/bytes_per_pkt))
    prev_pkt_cntr = None                         # init the packet counter
    lst_stream = []                              # make a list of lists of the float data
    headers = []                            # make a list of the packet headers
    dropped = []                            # make a list of any gaps in the packets

    show_status('streaming ...')
    time_start = time.clock()
    the_vx_ifc.write('STREAM ON')
    if b_use_threads:
        the_threads = []
        queue_drops = Queue.Queue()
        queue_data = Queue.Queue()            # decouple the printing/saving from the UDP socket
        for queue_func, queue_args in [(fill_queue, (the_udp_socket, queue_data, total_packets, bytes_per_pkt+4)),    #pylint: disable=line-too-long
                                       (empty_queue, (queue_data, queue_drops, total_packets, bytes_per_pkt, fmt_unpk, fmt_live_printing, s_channels, fname, bshow_status))]:   #pylint: disable=line-too-long
            the_threads.append(threading.Thread(target=queue_func, args=queue_args))
            # the_threads[-1].setDaemon(True)
            the_threads[-1].start()
        s_no_printing = '' if bshow_status else 'silently'
        print 'threads started %s\n'%s_no_printing
        the_threads[0].join(duration_stream+2)    # time out 2 seconds after the expected duration
        the_threads[1].join(duration_stream*2)    # time out 2x the duration more
        # queue_drops.get() blocks until empty_queue() writes to queue_drops showing it finished.
        dropped = queue_drops.get()
        print 'threads done'

    else:           # don't use threads. "block" instead
        for i in range(total_packets):
            # .recvfrom "blocks" program execution until all the bytes have been received.
            buf, _ = the_udp_socket.recvfrom(bytes_per_pkt+4)
            vals, head, n_dropped, prev_pkt_cntr = process_packet(buf, fmt_unpk, prev_pkt_cntr)
            lst_stream += [vals]
            headers += [head]
            dropped += [n_dropped]
            if bshow_status:
                show_status('dropped %4d of %d'%(sum(dropped), i), fmt_live_printing%tuple(lst_stream[-1][-len(s_channels):]))   #pylint: disable=line-too-long

        time_end = time.clock()
        if fname is not None:
            write_to_file(fname, s_channels, lst_stream)
        cleanup_ifcs()
        show_results(sum(dropped), total_packets, dropped, total_packets*bytes_per_pkt/(4*len(s_channels)))    #pylint: disable=line-too-long
        print 'Time elapsed: %.3f seconds'%(time_end-time_start)


if __name__ == '__main__':
    # group the docopt stuff to make it easier to remove, if desired
    dict_options = docopt.docopt(USE_STR, version='0.0.2')  #pylint: disable=invalid-name
    test(dict_options)
