# stream
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
 * open your comupter's firewall for incoming UDP on the streaming port. This script defaults to 1865 but any port that doesn't conflict with some other
service will work.
 * set the IP address of the SR865 to be visible to your computer and not conflict with other devices on your network.
 * use telnet to verify that your computer can connect to the SR865.
   * Type *idn? in telnet and you should see the identification string.
   * Exit telnet: Hold the control key and press ] to get to the telnet prompt, then type quit

Both of these things may require help from your local IT person. Once you've done these things, it's a good idea to edit the default settings in stream.py The settings start around line 66.
 * Change the default IP to match the setting in the SR865 Setup/Ethernet menu.
 * Make sure the UDP Port setting matches the opened port in your firewall.

