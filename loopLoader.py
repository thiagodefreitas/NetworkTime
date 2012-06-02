#!/usr/bin/env python

"""

loopLoader.py: This module plots the Offsets from the Loopstats file Generated on NTP runs.

"""

__author__ = "Thiago de Freitas Oliveira Araujo"
__copyright__ = "Copyright 2012, Google"
__credits__ = ["Judah Levine", "Harlan Stenn"]
__license__ = "GPL"
__version__ = "1.0"
__maintainer__ = "Thiago de Freitas"
__email__ = "thiago.oliveira@ee.ufcg.edu.br"
__status__ = "Prototype"

from scipy import *
import pylab
import allandev

class loopLoader():

    def __init__(self):

        self.Allan = allandev.AllanDev()


if __name__ == '__main__':

    file = open('loopstats.txt',"r")
    file2 = open("offsets.txt","w")


    offsets=[]
    seconds=[]

    readLines = file.readlines()

    for line in readLines:
        line = line.strip()
        line=line.split()
        offsets.append((float)(line[2]))
        seconds.append((float)(line[1]))

    for item in offsets:
        file2.write("%s\n" % item)

    allantest = loopLoader()
    [timeS, av, error] = allantest.Allan.allanDev(offsets, 10)



    pylab.figure(1)

    pylab.plot(seconds, offsets)
    pylab.title("Offsets Generated from a NTP trial run")
    pylab.grid(True)

    xMin = seconds[0]
    xMax = seconds[len(seconds)-1]

    xMin = (int)((floor)(xMin))

    xMax = (int)((floor)(xMax))

    pylab.xlim([xMin,xMax])

    pylab.figure(2)

    pylab.hist(offsets, histtype='step')
    pylab.title("Histogram of the Offsets")

    pylab.figure(3)

    pylab.xlabel(r'$\tau$')
    pylab.ylabel(r'$\sigma(\tau$)')
    pylab.title('Allan Standard Deviation')




    pylab.loglog(timeS, av, 'b^', timeS, av)
    pylab.errorbar(timeS, av,yerr=error,fmt='k.' )

    pylab.legend(('ADEV points', 'ADEV'))


    pylab.grid(True)

    pylab.show()