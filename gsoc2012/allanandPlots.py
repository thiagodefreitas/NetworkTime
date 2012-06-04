#!/usr/bin/env python

"""

allanandPlots.py: This module plots the Offsets from the estimators.py runs

"""

__author__ = "Thiago de Freitas Oliveira Araujo"
__copyright__ = "Copyright 2012, Google"
__credits__ = ["Judah Levine", "Harlan Stenn", "Antonio Lima"]
__license__ = "GPL"
__version__ = "1.0"
__maintainer__ = "Thiago de Freitas"
__email__ = "thiago.oliveira@ee.ufcg.edu.br"
__status__ = "Prototype"

from scipy import *
import pylab
import allandev

class allanandPlots():

    def __init__(self):
        self.Allan = allandev.AllanDev()


if __name__ == '__main__':

    file = open("computeTime_estimation.txt", "r")
    file2 = open("offsets_estimation.txt","r")


    offsets=[]
    seconds=[]


    readSeconds = file.readlines()
    readOffsets = file2.readlines()



    for line in readOffsets:
        line = line.strip()
        print line
        offsets.append((float)(line))

    for line2 in readSeconds:
        line2 = line2.strip()
        print line2
        seconds.append((float)(line2))

    print "offs",readOffsets
    print "secs", readSeconds

    allantest = allanandPlots()

    [timeS, av, error] = allantest.Allan.allanDev(offsets, 10)

    print mean(offsets)

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
