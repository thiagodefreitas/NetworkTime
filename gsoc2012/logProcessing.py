#!/usr/bin/env python

"""

logProcessing.py: This module plots the Offsets from the estimators.py runs

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
import scipy
import pylab
from time import ctime
from math import *
import allandev

class logProcessing():

    def __init__(self):

        self.Allan = allandev.AllanDev()



if __name__ == '__main__':

    file = open("estimators.log", "r")


    offsets=[]
    seconds=[]
    timeS = []
    av = []
    error = []

    readings = file.readlines()

    for line in readings:
        if "Logged" in line:
            line = line.strip()
            index_left = line.index("[")
            index_right = line.index("]")
            line = line[(int)(index_left)+1:(int)(index_right)]
            line = line.split(",")

            offsets.append((float)(line[1]))
            seconds.append((float)(line[3]))
        else:
            pass


    allantest = logProcessing()

    [timeS, av, error] = allantest.Allan.allanDev(offsets, 10)

    fileOffsets = open("offsetsLog.txt","w")

    for item in offsets:
        fileOffsets.write("%s\n" % item)


    pylab.figure(1)

    pylab.plot(seconds, offsets)
    pylab.title("Offsets Generated from a NTP trial run")
    pylab.grid(True)

    xMin = seconds[0]
    xMax = seconds[len(seconds)-1]

    xMin = (int)((floor)(xMin))

    xMax = (int)((floor)(xMax))

    pylab.xlim([xMin,xMax])

    toPlot = []
    toPlotTime = []

    for i in range(len(seconds)):
        if i%14 == 0:
            ct = ctime(seconds[i])
            ct = ct.split(' ')
            toPlot.append(ct[3])
            toPlotTime.append(seconds[i])

    pylab.xticks(toPlotTime, toPlot )

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
