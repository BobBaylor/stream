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
        You will certainly need to change the IP address to match your SR865 and for compatability with your network.

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
    import docopt           # handy command line parser. useStr (below) defines the syntax and documents it at the same time.
except ImportError:
    print 'python docopt library not found. Please install docopt or remove the docopt code from test() and main'


useStr = """
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


def showStatus(l='',r=''):
    """ Simple text status line that overwrites itself to prevent scrolling.
    """
    print ' %-30s %48s\r'%(l[:30],r[:48]),

# globals get assigned the udp and vxi11 objects to allow SIGINT to cleanup properly
udpSock = None
vx      = None

def cleanup():
    """ Stop the stream and close the socket and vxi11.
    """
    # global udpSock
    # global vx
    print "\n cleaning up...",
    vx.write('STREAM OFF')
    vx.close()
    udpSock.close()
    print 'connections closed\n'



def openInterfaces(ipadd,port):
    """ open a UDP socket and a vxi11 instrument and assign them to the globals
    """
    global udpSock
    global vx
    print'\nopening incoming UDP Socket at %d ...' % port,
    udpSock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udpSock.bind(('',port))                               # listen to anything arriving on this port from anyone
    print 'done'
    print'opening VXI-11 at %s ...' % ipadd,
    vx = vxi11.Instrument(ipadd)
    vx.write('STREAMPORT %d'%port)
    print 'done'



def dutConfig(vx,sStrChans,iPktLenIdx,fRateTarget,fDuration,bInt):
    """ Setup the SR865 for streaming. Return the total expected sample count
    """
    vx.write('STREAM OFF')                          # turn off streaming while we set it up
    vx.write('STREAMCH %s'%sStrChans)
    if bInt:
        vx.write('STREAMFMT 1')                 # 16 bit int
    else:
        vx.write('STREAMFMT 0')                 # 32 bit float
    vx.write('STREAMOPTION 2')              # use big-endian (~1) and data integrity checking (2)
    vx.write('STREAMPCKT %d'%iPktLenIdx)
    fRateMax = float(vx.ask('STREAMRATEMAX?'))      # filters determine the max data rate

    iRateDeci = int(math.ceil(math.log(fRateMax/fRateTarget, 2.0)))    # calculate a decimation to stay under fRateTarget
    if iRateDeci < 0:
        iRateDeci = 0
    if iRateDeci > 20:
        iRateDeci = 20

    fRate     = fRateMax/(2.0**iRateDeci)
    print'Max rate is %.3f kS/S. Decimating by 2^%d down to %.3f kS/S'%(fRateMax*1e-3,iRateDeci,fRate*1e-3)
    vx.write('STREAMRATE %d'%iRateDeci)     # bring the rate under our target rate
    fSamps = fDuration*fRate
    return fSamps


def writeToFile(fname,sStrChans,xData):
    """ Save data to a comma separated file. We could also use the csv python module...
    """
    showStatus('writing %s ...'%fname)
    with open(fname,'w') as fl:
        fl.write(''.join(['%s,'%str.upper(v) for v in sStrChans])+'\n')
        if type(xData[0][0]) is float:
            fFmt = '%+12.6e,'*len(sStrChans)
        else:
            fFmt = '%+d,'*len(sStrChans)
        for p in xData:
            for i in range(0,len(p),len(sStrChans)):
                x = p[i:i+len(sStrChans)]
                fl.write(fFmt%tuple(x)+'\n')
    showStatus('%s written'%fname)



# socket seems to catch the KeyboardInterrupt exception if I don't grab it explicitly here
def interrupt_handler(signum, frame):
    cleanup()
    sys.exit(-2)      #Terminate process here as catching the signal removes the close process behaviour of Ctrl-C

signal.signal(signal.SIGINT, interrupt_handler)


# thread functions ----------------------------------------------
def fillQueue(s,q,cntP,cntB):
    """ Pump packets from the socket (SR865) to the python dataQueue
    """
    for i in range(cntP):
        buf, _ = s.recvfrom(cntB)
        q.put(buf)
    cleanup()


def processPacket(buf,upFmt,prevCntr):
    """ Unpack the header and data froma packet, checking for dropped packets.
        return the data, the header, the number of packets missed, and the current packet number.
        Only the packet counter is checked - other, possibly important information in the header (such
        as overload, unlock status, data type, streamed variables, and sample rate) are ignored.
    """
    vals = list(unpack_from(upFmt,buf,4))      # convert to floats or ints after skipping 4 bytes of header
    head = unpack_from('>I',buf)[0]            # convert the header to an 32 bit int
    cntr = head & 0xff                         # extract the packet counter from the header
    if prevCntr is not None and ((prevCntr+1)&0xff) != cntr:   # if this isn't the 1st and the difference isn't 1 then
        dcnt = cntr - prevCntr                                 # calculate how many we missed
        if dcnt < 0:
            dcnt += 0xff
    else:
        dcnt = 0
    return vals, head, dcnt, cntr


def emptyQueue(qDat,qDrop,cntP,cntB,upFmt,fmtPrt,sStrChans,fname,bShowStatus):
    """ myThreads[1] calls this to pull data out of the dataQueue.
        When all the packets have been processed:
            writes to a file (optional)
            displays the dropped packet stats
            writes the drop list (maybe empty) to qDrop.
    """
    prevCntr = None                         # init the packet counter
    dropL = []                            # make a list of any missing packets
    dropTotal = 0
    xData = []
    cntV = len(sStrChans)
    for i in range(cntP):
        buf = qDat.get()
        vals, _, dcnt, prevCntr = processPacket(buf,upFmt,prevCntr)
        xData += [vals]
        if dcnt:
            dropL += [(dcnt,i)]
        dropTotal += dcnt
        if bShowStatus:
            showStatus('dropped %4d of %d'%(dropTotal,i+1),fmtPrt%tuple(xData[-1][-cntV:]))

    if fname is not None:
        writeToFile(fname,sStrChans,xData)

    if dropTotal:
        print '\nFAIL: Dropped %d out of %d packets in %d gaps:'%(dropTotal,cntP,len(dropL)),
        print ''.join( '%d at %d, '%(x[0],x[1]) for x in dropL[:5])
    else:
        print '\npass: No packets dropped out of %d. %d samples captured.'%(cntP,cntP*cntB/(4*cntV))
    qDrop.put(dropL)    # signal to main thread that we finished the post-processing


# the main program -----------------------------------------------
def test(opts):
    # global udpSock
    # global vx

    # group the docopt stuff to make it easier to remove, if desired
    dutAdd  = opts['--address']               # IP address and streaming port of the SR865
    dutPort = int(opts['--port'])
    fRateTarget = float(opts['--rate'])       # sample rate that host wants. Actual rate will be below this and depends on filter settings
    iPktLenIdx = int(opts['--length'])        # select the packet size: 0 to 3 select 1024..128 byte packets
    fDuration = float(opts['--duration'])     # in seconds
    bShowStatus = not opts['--silent']
    fname = opts['--file']
    sStrChans = str(opts['--vars'])           # what to stream. X, XY, RT, or XYRT allowed
    vAllowed = ['X','XY','RT','XYRT']
    bInts = opts['--ints']
    bUseThreads = opts['--thread']

    if not sStrChans.upper() in vAllowed:
        print '--vars option was %s. Must be one of'%sStrChans.upper(),', '.join(vAllowed)
        sys.exit(-1)

    openInterfaces(dutAdd,dutPort)
    fSamps = dutConfig(vx,sStrChans,iPktLenIdx,fRateTarget,fDuration,bInts)
    iPktBytes = [1024,512,256,128][iPktLenIdx]       # translate the packet size enumeration into an actual byte count
    if bInts:
        upFmt = '>%dh'%(iPktBytes/2)            # create an unpacking format string.
        statRFmt = '%12d'*len(sStrChans)        # create status format string.
    else:
        upFmt = '>%df'%(iPktBytes/4)
        statRFmt = '%12.6f'*len(sStrChans)

    iPktCnt = int(math.ceil(fSamps*4*len(sStrChans)/iPktBytes))
    prevCntr = None                         # init the packet counter
    xData = []                              # make a list of lists of the float data
    headers = []                            # make a list of the packet headers
    dropped = []                            # make a list of any gaps in the packets

    showStatus('streaming ...')
    timeS = time.clock()
    vx.write('STREAM ON')
    if bUseThreads:
        myThreads = []
        dropsQueue = Queue.Queue()
        dataQueue = Queue.Queue()            # decouple the printing/saving from the UDP socket
        for t,a in [(fillQueue, (udpSock,dataQueue,iPktCnt,iPktBytes+4)),
                    (emptyQueue,(dataQueue,dropsQueue,iPktCnt,iPktBytes,upFmt,statRFmt,sStrChans,fname,bShowStatus))]:
            myThreads.append( threading.Thread(target=t,args=a))
            # myThreads[-1].setDaemon(True)
            myThreads[-1].start()
        statStr = '' if bShowStatus else 'silently'
        print 'threads started %s\n'%statStr
        myThreads[0].join(fDuration+2)      # times out 2 seconds after the expected stream duration
        myThreads[1].join(fDuration*2)      # times out 2x the duration more
        dropped = dropsQueue.get()  # blocks until emptyQueue() writes to dropsQueue signalling it finished.
        print 'threads done'
    else:
        for i in range(iPktCnt):
            buf, _ = udpSock.recvfrom(iPktBytes+4)      # this "blocks" program execution until all the bytes have been received.
            vals, head, dcnt, prevCntr = processPacket(buf,upFmt,prevCntr)
            xData += [vals]
            headers += [head]
            dropped += [dcnt]
            if bShowStatus:
                showStatus('dropped %4d of %d'%(sum(dropped),i),statRFmt%tuple(xData[-1][-len(sStrChans):]))

        timeE = time.clock()
        if fname is not None:
            writeToFile(fname,sStrChans,xData)
        cleanup()
        if sum(dropped):
            print '\nFAIL: Dropped %d out of %d packets in %d gaps'%(sum(dropped),iPktCnt,len(dropped))
        else:
            print '\npass: No packets dropped out of %d. %d %s samples captured in %.3f seconds.'%(iPktCnt,iPktCnt*iPktBytes/(4*len(sStrChans)),sStrChans,timeE-timeS)


if __name__ == '__main__':
    # group the docopt stuff to make it easier to remove, if desired
    opts = docopt.docopt(useStr,version='0.0.2')
    test(opts)

