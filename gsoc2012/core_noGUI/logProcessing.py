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

import numpy as np

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

        self.offsets = []
        self.seconds = []
        self.secondsPure = []

        for line in readings:
            if "Logged" in line:
                line = line.strip()
                index_left = line.index("[")
                index_right = line.index("]")
                line = line[(int)(index_left)+1:(int)(index_right)]
                line = line.split(",")

                self.offsets.append((float)(line[1]))
                self.secondsPure.append((float)(line[3]))

                if(len(self.seconds) > 0):
                    self.seconds.append((float)(line[3])-self.seconds[0])
                else:
                    self.seconds.append((float)(line[3]))
            else:
                pass

        self.seconds[0] = 0


        self.file.close()


    def plotnoGui(self):

        pylab.figure(1)

        pylab.xlabel('Time(s)')
        pylab.ylabel('Offsets(s)')

        pylab.plot(self.seconds, self.offsets)
        pylab.title("Offsets Generated from a NTP trial run")
        pylab.grid(True)

       # xMin = 0
       # xMax = (float)(self.offsets[-1])


#        xMin = (int)((floor)(xMin))

 #       xMax = (int)((floor)(xMax))

#        pylab.xlim([xMin,xMax])

        toPlot = []
        toPlotTime = []

    #    for i in range(len(self.seconds)):
        #    if i%14 == 0:
             #   ct = ctime(self.seconds[i])
              #  ct = ct.split(' ')
             #   toPlot.append(ct[3])
              #  toPlotTime.append(self.seconds[i])

        #pylab.xticks(toPlotTime, toPlot )

        pylab.figure(2)

      #  pylab.hist(self.offsets, histtype='step')
       # pylab.title("Histogram of the Offsets")

        pylab.xlabel('Seconds(s)')
        pylab.ylabel('Residuals(s)')


        secArray = np.asarray(self.seconds)
        offArray = np.asarray(self.offsets)
        a,b = np.polyfit(secArray,offArray,1)



        residualsArray =  offArray-(a*secArray+b)

        pylab.plot(secArray,residualsArray , '--k')

        pylab.figure(3)

        pylab.xlabel(r'$\tau$ - sec')
        pylab.ylabel(r'$\sigma(\tau$)')
        pylab.title('Allan Standard Deviation')




        pylab.loglog(self.timeS, self.av, 'b^', self.timeS, self.av)
        pylab.errorbar(self.timeS, self.av,yerr=self.error,fmt='k.' )

        pylab.legend(('ADEV points', 'ADEV'))


        pylab.grid(True)


        pylab.figure(4)

        pylab.xlabel('Seconds(s)')
        pylab.ylabel('Residuals(s)')




        offsetsMod = zeros(9)
        offs = np.asarray(self.offsets)
        offsetsMod = np.concatenate((offsetsMod,offs))

        offsetsAgain =[]
        secAgain = []
    #Checking the Allan Deviation for Abnormal Values
        for i in range(10,len(self.offsets)):
            [time1, av1, err1] = allantest.Allan.allanDevMills(offsetsMod[i-10:i])

            if (av1[0] > 0.00035):
                print "OK!!"
            else:
                offsetsAgain.append(self.offsets[i-10])
                secAgain.append(self.seconds[i-10])




        secArray = np.asarray(secAgain)
        offArray = np.asarray(offsetsAgain)
        a,b = np.polyfit(secArray,offArray,1)



        residualsArray =  offArray-(a*secArray+b)

        pylab.plot(secArray,residualsArray , '--k')



        pylab.figure(5)

        [time1, av1, err1] = allantest.Allan.allanDevMills(offsetsAgain)

        pylab.xlabel(r'$\tau$ - sec')
        pylab.ylabel(r'$\sigma(\tau$)')
        pylab.title('Allan Standard Deviation')




        pylab.loglog(time1, av1, 'b^', time1, av1)
        pylab.errorbar(time1, av1,yerr=err1,fmt='k.' )

        pylab.legend(('ADEV points', 'ADEV'))


        pylab.grid(True)

        pylab.figure(6)

        [time1, av1, err1] = allantest.Allan.allanDevMills(offsetsAgain)

        pylab.xlabel(r'$\tau$ - sec')
        pylab.ylabel(r'$\sigma(\tau$) - PPM')
        pylab.title('Allan Standard Deviation')




        pylab.loglog(time1, np.asarray(av1)*1e6, 'b^', time1, np.asarray(av1) *1e6)
        pylab.errorbar(time1, np.asarray(av1)*1e6,yerr=np.asarray(err1)*1e6,fmt='k.')

        pylab.legend(('ADEV points', 'ADEV'))


        pylab.grid(True)





        pylab.figure(7)

        storageOFFs = []

        offArray2 = offsetsAgain[7::8]
        secArray2 = secAgain[7::8]


        pylab.xlabel('Seconds(s)')
        pylab.ylabel('Corrected Offset(s)')



        for i in range(len(offArray2)):





            correction = a*secArray2[i] + b

            storageOFFs.append(offArray2[i] - correction)


        pylab.plot(secArray2,storageOFFs)


        pylab.grid(True)



        pylab.show()



if __name__ == '__main__':

    allantest = logProcess()

    allantest.processLog("run_ubuntu.log")

    [allantest.timeS, allantest.av, allantest.error] = allantest.Allan.allanDevMills(allantest.offsets)



    fileOffsets = open("offsetsLog.txt","w")

    for item in allantest.offsets:
        fileOffsets.write("%s\n" % item)


    fileSeconds = open("secondsLog.txt","w")


    for item in allantest.seconds:
        fileSeconds.write("%s\n" % item)


    allantest.plotnoGui()