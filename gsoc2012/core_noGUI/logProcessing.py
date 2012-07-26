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
        self.timeStep1 = False

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

        pylab.savefig('offsets.pdf')

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

        pylab.savefig('residuals.pdf')

        pylab.figure(3)

        pylab.xlabel(r'$\tau$ - sec')
        pylab.ylabel(r'$\sigma(\tau$) - sec')
        pylab.title('Allan Standard Deviation')




        pylab.loglog(self.timeS, self.av, 'b^', self.timeS, self.av)
        pylab.errorbar(self.timeS, self.av,yerr=self.error,fmt='k.' )

        pylab.legend(('ADEV points', 'ADEV'))


        pylab.grid(True)

        pylab.savefig('adev.pdf')


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
                pass
            else:
                offsetsAgain.append(self.offsets[i-10])
                secAgain.append(self.seconds[i-10])

        # New tests for the Middle Data of the Run Ubuntu Estimator

        offMidMod = zeros(9)
        offsMiddle =  self.offsets[250:301]
        offMidMod = np.concatenate((offMidMod,offsMiddle))

        offsetsMiddle = np.asarray(self.offsets)
        secMiddle = np.asarray(self.seconds)

        for i in range(10,len(offsMiddle)):
            [time2, av2, err2] = allantest.Allan.allanDevMills(offMidMod[i-10:i])



        secArray = np.asarray(secAgain)
        offArray = np.asarray(offsetsAgain)
        a,b = np.polyfit(secArray,offArray,1)



        residualsArray =  offArray-(a*secArray+b)

        pylab.plot(secArray,residualsArray , '--k')

        pylab.savefig('Residualscorrected.pdf')

        pylab.figure(5)

        [time1, av1, err1] = allantest.Allan.allanDevMills(offsetsAgain)

        pylab.xlabel(r'$\tau$ - sec')
        pylab.ylabel(r'$\sigma(\tau$) - sec')
        pylab.title('Allan Standard Deviation')




        pylab.loglog(time1, av1, 'b^', time1, av1)
        pylab.errorbar(time1, av1,yerr=err1,fmt='k.' )

        pylab.legend(('ADEV points', 'ADEV'))


        pylab.grid(True)

        pylab.savefig('Allancorrected.pdf')

        pylab.figure(6)

        [time1, av1, err1] = allantest.Allan.allanDevMills(offsetsAgain)

        pylab.xlabel(r'$\tau$ - sec')
        pylab.ylabel(r'$\sigma(\tau$) - PPM')
        pylab.title('Allan Standard Deviation')




        pylab.loglog(time1, np.asarray(av1)*1e6, 'b^', time1, np.asarray(av1) *1e6)
        pylab.errorbar(time1, np.asarray(av1)*1e6,yerr=np.asarray(err1)*1e6,fmt='k.')

        pylab.legend(('ADEV points', 'ADEV'))


        pylab.grid(True)



        pylab.savefig('AllancorrectedPPM.pdf')

        pylab.figure(7)

        storageOFFs = []

        div = 3

        print len(offsetsAgain), len(secAgain)

        secAgainT = secAgain[0:(len(secAgain)/div)]

        offsetsAgainT = offsetsAgain[0:(len(offsetsAgain)/div)]

        secArray = np.asarray(secAgainT)
        offArray = np.asarray(offsetsAgainT)

        a,b = np.polyfit(secArray,offArray,1)
        # Using only 1/8 of the data
        offArray2 = offsetsAgain[(len(secAgain)/div)::8]
        secArray2 = secAgain[(len(secAgain)/div)::8]


        pylab.xlabel('Seconds(s)')
        pylab.ylabel('Corrected Offset(s)')



        for i in range(len(offArray2)):





            correction = a*secArray2[i] + b
            offNew = offArray2[i] - correction
            storageOFFs.append(offNew)

            secAgainT.pop(0)
            offsetsAgainT.pop(0)

            secAgainT.append(secArray2[i])
            offsetsAgainT.append(offArray2[i])


            secArray = np.asarray(secAgainT)
            offArray = np.asarray(offsetsAgainT)

            a,b = np.polyfit(secArray,offArray,1)


        pylab.plot(secArray2,storageOFFs)


        pylab.grid(True)

        pylab.savefig('corrected.pdf')






        pylab.figure(8)


        pylab.plot(secMiddle,offsetsMiddle)

        pylab.xlabel('Seconds(s)')
        pylab.ylabel('Corrected Offset(s)')


        pylab.figure(9)


        secArray = np.asarray(secAgain)
        offArray = np.asarray(offsetsAgain)
        a,b = np.polyfit(secArray,offArray,1)



        residualsArray =  offArray-(a*secArray+b)


        #diffs = diff(residualsArray)
        diffs = zeros(len(residualsArray)-1)
        # d = 0
        for i in range(1,len(residualsArray)):

            diffs[i-1] = residualsArray[i] - residualsArray[i-1]



            if diffs[i-1] > av2[0]:



                if(self.timeStep1):
                    residualsArray[i-1] =  av2[0]*1024
                    residualsArray[i] = residualsArray[i] - residualsArray[i-1]
                    print residualsArray[i]

                self.timeStep1=True

            else:

                self.timeStep1 = False


            #        while(d < len(diffs)):
            #
            #            if(self.timeStep1):
            #                diffs[d-1] =  av2[0]
            #                temp = diff(diffs[d-1:d+1])
            #                print temp
            #                diffs[d] = temp
            #                print diffs[d], av2[0]
            #
            #
            #            if(diffs[d] > 3*av2[0]):
            #
            #                self.timeStep1 = True
            #
            #
            #
            #            else:
            #                self.timeStep1 = False
            #
            #
            #
            #
            #
            #
            #
            #
            #                #diffs = np.delete(diffs, d)
            #                #offsetsMiddle = np.delete(offsetsMiddle, d)
            #                #secMiddle = np.delete(secMiddle,d)
            #
            #            d += 1
            ##
            ##            if(diffs[d] > 3*av2[0]):
            ##
            ##                diffs = np.delete(diffs, d)
            ##                offsetsMiddle = np.delete(offsetsMiddle, d)
            ##                secMiddle = np.delete(secMiddle,d)
            ##
            ##            d += 1


        pylab.plot(secArray,residualsArray , '--k')
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