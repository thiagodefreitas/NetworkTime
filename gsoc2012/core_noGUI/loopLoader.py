#!/usr/bin/env python

"""

loopLoader.py: This module plots the Offsets from the Loopstats file Generated on NTP runs.

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

import numpy as np

class loopLoader():

    def __init__(self):

        self.Allan = allandev.AllanDev()
        self.offsets = []
        self.seconds = []
        self.timeS = []
        self.av = []
        self.error = []
        self.day = []

        self.file = None
        self.file2 = None

    def processLoopStats(self, fName):

        self.file = open(fName, "r")

        readLines = self.file.readlines()

        self.offsets = []
        self.seconds = []
        self.secondsPure=[]
        self.day = []

        for line in readLines:
            line = line.strip()
            line=line.split()
            self.day.append((float)(line[0]))
            self.offsets.append((float)(line[2]))
            self.secondsPure.append((float)(line[1]))
            self.seconds.append((float)(line[1]))

        self.file.close()


    def savetoFile(self, fName):

        self.file2 = open(fName, "w")
        for item in self.offsets:
            self.file2.write("%s\n" % item)

        self.file2.close()

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

        #PPM PLOT

       # pylab.loglog(self.timeS, np.asarray(self.av)*1e6, 'b^', self.timeS, np.asarray(self.av) *1e6)
       # pylab.errorbar(self.timeS, np.asarray(self.av)*1e6,yerr=np.asarray(self.error),fmt='k.' )

        #pylab.legend(('ADEV points', 'ADEV'))


        #pylab.grid(True)

        #pylab.show()





if __name__ == '__main__':

    allantest = loopLoader()
    allantest.processLoopStats('loopstats.txt')
    allantest.savetoFile("offsets.txt")
    #[allantest.timeS, allantest.av, allantest.error] = allantest.Allan.allanDev(allantest.offsets, 10)
    [allantest.timeS, allantest.av, allantest.error] = allantest.Allan.allanDevMills(allantest.offsets)
    allantest.plotnoGui()