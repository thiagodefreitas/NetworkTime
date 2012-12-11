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
        self.offsets = []
        self.seconds = []
        self.timeS = []
        self.av = []
        self.error = []

        self.file = None
        self.file2 = None


    def processOffsets(self, fName, fName2):

        self.file = open(fName, "r")
        self.file2 = open(fName2, "r")

        self.offsets = []
        self.seconds = []
        self.secondsPure =[]

        readSeconds = self.file.readlines()
        readOffsets = self.file2.readlines()

        for line in readOffsets:
            line = line.strip()
            self.offsets.append((float)(line))

        for line2 in readSeconds:
            line2 = line2.strip()

          #  self.secondsPure.append((float)(line[2]))

            if(len(self.seconds) > 0):

                self.seconds.append((float)(line2)-self.seconds[0])

            else:

                self.seconds.append((float)(line2))

        print self.seconds

        self.seconds[0] = 0


    def plotnoGui(self):

        pylab.figure(1)

        pylab.plot(self.seconds, self.offsets)
        pylab.ylabel("Offsets(seconds)")
        pylab.xlabel("Time elapsed(seconds)")
        pylab.title("Offsets Generated from a NTP trial run")
        pylab.grid(True)

       # xMin = self.seconds[0]
       # xMax = self.seconds[len(self.seconds)-1]

        #xMin = (int)((floor)(xMin))

       # xMax = (int)((floor)(xMax))

       # pylab.xlim([xMin,xMax])


        pylab.figure(2)

        pylab.hist(self.offsets, histtype='step')
        pylab.title("Histogram of the Offsets")

        pylab.figure(3)

        pylab.xlabel(r'$\tau$(sec)')
        pylab.ylabel(r'$\sigma(\tau$)(sec/sec)')
        pylab.title('Allan Standard Deviation')




        pylab.loglog(self.timeS, self.av, 'b^', self.timeS, self.av)
        pylab.errorbar(self.timeS, self.av,yerr=self.error,fmt='k.' )

        pylab.legend(('ADEV points', 'ADEV'))


        pylab.grid(True)

        pylab.show()





if __name__ == '__main__':


    allantest = allanandPlots()
    allantest.processOffsets("computeTime_estimation.txt","offsets_estimation.txt")

    [allantest.timeS, allantest.av, allantest.error] = allantest.Allan.allanDevMills(allantest.offsets)

    print mean(allantest.offsets)

    allantest.plotnoGui()