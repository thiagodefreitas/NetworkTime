#!/usr/bin/env python

"""

logProcessing.py: This module plots the Offsets from the estimators.py runs

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
import scipy
import pylab
from time import ctime
from math import *
import allandev

class logProcess():

    def __init__(self):

        self.Allan = allandev.AllanDev()
        self.offsets = []
        self.seconds = []
        self.timeS = []
        self.av = []
        self.error = []

        self.file = None

    def processLog(self, fName):

        self.file = open(fName, "r")

        readings = self.file.readlines()



        for line in readings:
            if "Logged" in line:
                line = line.strip()
                index_left = line.index("[")
                index_right = line.index("]")
                line = line[(int)(index_left)+1:(int)(index_right)]
                line = line.split(",")

                self.offsets.append((float)(line[1]))
                self.seconds.append((float)(line[3]))
            else:
                pass

        self.file.close()


    def plotnoGui(self):

        pylab.figure(1)

        pylab.plot(self.seconds, self.offsets)
        pylab.title("Offsets Generated from a NTP trial run")
        pylab.grid(True)

        xMin = self.seconds[0]
        xMax = self.seconds[len(self.seconds)-1]

        xMin = (int)((floor)(xMin))

        xMax = (int)((floor)(xMax))

        pylab.xlim([xMin,xMax])

        toPlot = []
        toPlotTime = []

        for i in range(len(self.seconds)):
            if i%14 == 0:
                ct = ctime(self.seconds[i])
                ct = ct.split(' ')
                toPlot.append(ct[3])
                toPlotTime.append(self.seconds[i])

        pylab.xticks(toPlotTime, toPlot )

        pylab.figure(2)

        pylab.hist(self.offsets, histtype='step')
        pylab.title("Histogram of the Offsets")


        pylab.figure(3)

        pylab.xlabel(r'$\tau$')
        pylab.ylabel(r'$\sigma(\tau$)')
        pylab.title('Allan Standard Deviation')




        pylab.loglog(self.timeS, self.av, 'b^', self.timeS, self.av)
        pylab.errorbar(self.timeS, self.av,yerr=self.error,fmt='k.' )

        pylab.legend(('ADEV points', 'ADEV'))


        pylab.grid(True)

        pylab.show()



if __name__ == '__main__':

    allantest = logProcess()

    allantest.processLog("estimators.log")

    [allantest.timeS, allantest.av, allantest.error] = allantest.Allan.allanDev(allantest.offsets, 10)

    fileOffsets = open("offsetsLog.txt","w")

    for item in allantest.offsets:
        fileOffsets.write("%s\n" % item)

    allantest.plotnoGui()