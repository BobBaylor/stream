There are two scripts in this repo: stream.py and cap860.py They both collect data from an SRS lock-in amplifier. 
 * stream does it in real-time using UDP over an ethernet connection. 
 * cap860 uses the lock-in capture buffer before downloading the data to the host computer.
 
cap860.py is detailed after stream.py
## Which one should I use?
 * stream.py uses UDP which may drop packets (data) depending on network traffic so if missing data is a problem, 
 you might want to use cap860.py
 * cap860.py transfers using TCP/IP so packets are re-transmitted as needed and no data is lost. However, 
 the cap860.py transfer hapens after the data collection is complete so you must wait until the end.
 
# stream.py
## What is this?
This python script streams data from a Stanford Research Systems SR865, SR865A, or SR860 lock-in amplifier.
## What's a lock-in amplifier?
A lock-in is a scientific instrument for measuring the phase and amplitude of a signal at a specific frequency.
It uses a Phase Synchronous Detector (PSD) to extract the in-phase and quadrature components of the signal.
[This application note](http://www.thinksrs.com/downloads/PDFs/ApplicationNotes/AboutLIAs.pdf) explains it in much more detail.
## How do I run this script?
You need a few things:
 * A computer with python
   * I've tested this with python 2.7
   * you'll need to install vxi11 using pip, brew, or whatever installation tool you use.
   * The script parses command line arguments with docopt, so you'll need to install that, too.
 * an [SR865](http://www.thinksrs.com/products/SR865A.htm), SR865A or SR860.
 * a network connection between the two.

## Is that all?
You also need to
 * open your comupter's firewall for incoming UDP on the streaming port. This script defaults to 1865 but any port that 
 doesn't conflict with some other service will work.
 * set the IP address of the SR865 to be visible to your computer and not conflict with other devices on your network.
 * use telnet to verify that your computer can connect to the SR865.
   * Type *idn? in telnet and you should see the identification string.
   * Exit telnet: Hold the control key and press ] to get to the telnet prompt, then type quit

Both of these things may require help from your local IT person. Once you've done these things, 
it's a good idea to edit the default settings in stream.py The settings start around line 66.
 * Change the default IP to match the setting in the SR865 Setup/Ethernet menu.
 * Make sure the UDP Port setting matches the opened port in your firewall.

# cap860.py
## What is this?
This python script configures the instrument to capture data internally and, when complete, download it to the host computer. 
## How do I run this script?
You need all the things mentioned for stream.py, above

## Is that all?
Like stream.py, you *do* need to set the instrument IP address but you *do not* need to open a port in your firewall. Follow the instructions for stream but ignore the stuff about the port.
