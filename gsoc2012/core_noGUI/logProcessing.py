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

import ransac

from ransac import *

import numpy as np


def ransac_modified(data,model,n,k,t,d,debug=False,return_all=False):
    """fit model parameters to data using the RANSAC algorithm

This implementation written from pseudocode found at
http://en.wikipedia.org/w/index.php?title=RANSAC&oldid=116358182

{{{
Given:
    data - a set of observed data points
    model - a model that can be fitted to data points
    n - the minimum number of data values required to fit the model
    k - the maximum number of iterations allowed in the algorithm
    t - a threshold value for determining when a data point fits a model
    d - the number of close data values required to assert that a model fits well to data
Return:
    bestfit - model parameters which best fit the data (or nil if no good model is found)
iterations = 0
bestfit = nil
besterr = something really large
while iterations < k {
    maybeinliers = n randomly selected values from data
    maybemodel = model parameters fitted to maybeinliers
    alsoinliers = empty set
    for every point in data not in maybeinliers {
        if point fits maybemodel with an error smaller than t
             add point to alsoinliers
    }
    if the number of elements in alsoinliers is > d {
        % this implies that we may have found a good model
        % now test how good it is
        bettermodel = model parameters fitted to all points in maybeinliers and alsoinliers
        thiserr = a measure of how well model fits these points
        if thiserr < besterr {
            bestfit = bettermodel
            besterr = thiserr
        }
    }
    increment iterations
}
return bestfit
}}}
"""
    iterations = 0
    bestfit = None
    besterr = numpy.inf
    best_inlier_idxs = None
    while iterations < k:
        maybe_idxs, test_idxs = random_partition(n,data.shape[0])
        maybeinliers = data[maybe_idxs,:]
        test_points = data[test_idxs]
        maybemodel = model.fit(maybeinliers)
        test_err = model.get_error( test_points, maybemodel)
        also_idxs = test_idxs[test_err < t] # select indices of rows with accepted points
        alsoinliers = data[also_idxs,:]
        if debug:
            print 'test_err.min()',test_err.min()
            print 'test_err.max()',test_err.max()
            print 'numpy.mean(test_err)',numpy.mean(test_err)
            print 'iteration %d:len(alsoinliers) = %d'%(
                iterations,len(alsoinliers))
        if len(alsoinliers) > d:
            betterdata = numpy.concatenate( (maybeinliers, alsoinliers) )
            mi = np.hsplit(maybeinliers,2)
            ai = np.hsplit(alsoinliers,2)

            betterdatatoAllan = numpy.concatenate((mi[1], ai[1]))
            betterdatatoAllan = reshape(betterdatatoAllan, len(betterdatatoAllan))
            bettermodel = model.fit(betterdata)
            better_errs = model.get_error( betterdata, bettermodel)
            thiserr = numpy.mean( better_errs )
            [timeA, thisallan, thiserrA] = allantest.Allan.allanDevMills(betterdatatoAllan)
            if (thisallan[0]) < 0.00035:
                bestfit = bettermodel
                besterr = thiserr
                best_inlier_idxs = numpy.concatenate( (maybe_idxs, also_idxs) )
        iterations+=1
    if bestfit is None:
        raise ValueError("did not meet fit acceptance criteria")
    if return_all:
        return bestfit, {'inliers':best_inlier_idxs}
    else:
        return bestfit

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
        pylab.ylabel(r'$\sigma(\tau$)')
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

            if (av1[0] > 0.00020):
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
        pylab.ylabel(r'$\sigma(\tau$)')
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


        secArray = np.asarray(secAgain)
        offArray = np.asarray(offsetsAgain)
        a,b = np.polyfit(secArray,offArray,1)



        residualsArray =  offArray-(a*secArray+b)

        #diffs = diff(residualsArray)
        diffs = zeros(len(residualsArray)-1)
        # d = 0
        offinho = offArray
        for i in range(1,len(offinho)):

            diffs[i-1] = offinho[i] - offinho[i-1]



            if diffs[i-1] > 3*av2[0]:



                if(self.timeStep1):
                    offinho[i-1] =  av2[0]*1024
                    offinho[i] = offinho[i] - offinho[i-1]


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


        pylab.plot(secArray,offinho , '--k')

        pylab.figure(13)

        [time1, av1, err1] = allantest.Allan.allanDevMills(diffs)

        pylab.xlabel(r'$\tau$ - sec')
        pylab.ylabel(r'$\sigma(\tau$)')
        pylab.title('Allan Standard Deviation')


        pylab.loglog(time1, av1, 'b^', time1, av1)
        pylab.errorbar(time1, av1,yerr=err1,fmt='k.' )

        pylab.legend(('ADEV points', 'ADEV'), loc=2)


        pylab.grid(True)

        pylab.figure(10)


        secArray = np.asarray(self.seconds)
        offArray = np.asarray(self.offsets)

        #offArray = offArray-offArray[0]

        a,b = np.polyfit(secArray,offArray,1)



        residualsArray =  offArray-(a*secArray+b)



        ###################
        # Testing Ransac Fit for the Data

        residualsArray.shape = (len(residualsArray),1)
        secArray.shape = (len(secArray),1)
        offArray.shape = (len(offArray),1)
        n_inputs = 1

        n_outputs = 1

        all_data = numpy.hstack( (secArray,offArray) )


        input_columns = range(n_inputs)

        output_columns = [n_inputs+i for i in range(n_outputs)]

        model = LinearLeastSquaresModel(input_columns,output_columns)

        ransac_fit, ransac_data = ransac(all_data,model,90, 1000, 10, 10, debug=1,return_all=True)

        linear_fit,resids,rank,s = scipy.linalg.lstsq(all_data[:,input_columns],
            all_data[:,output_columns])

        sort_idxs = numpy.argsort(secArray[:,0])
        ar1_col0_sorted = secArray[sort_idxs] # maintain as rank-2 array
# numpy.dot(ar1_col0_sorted, linear_fit) [:, 0]

        fitted_ransac = numpy.dot(ar1_col0_sorted, ransac_fit)[:, 0] + self.offsets[0]
        fitted_ransac = offArray[:,0] - fitted_ransac

        lin_fit = a*secArray+b


        pylab.plot(secArray, fitted_ransac, label='RANSAC fit')
        pylab.plot(secArray,a*secArray+b, label='linear fit')


        pylab.plot(secArray, offArray ,'k.', label='noisy data')


        pylab.legend()

        pylab.figure(11)



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

        for item in offsetsAgain:
            item = item - offsetsAgain[0]

        diffs = diff(offsetsAgain)

        diffs = np.asarray(diffs)
        offArray = np.asarray(offsetsAgain)
        secArray = np.asarray(secAgain)
        s = secArray[1:,]
        offArray.shape = (len(offArray),1)
        print s.shape, diffs.shape

        diffs.shape = (len(diffs), 1)

        s.shape = (len(s),1)


        all_data = numpy.hstack( (s,diffs) )

        #n - the minimum number of data required to fit the model
        #k - the number of iterations performed by the algorithm
        #t - a threshold value for determining when a datum fits a model
        #d - the number of close data values required to assert that a model fits well to data

        ransac_fit, ransac_data = ransac(all_data,model,20, 222, 0.2, 10, debug=1,return_all=True)
        diffs.shape = len(diffs)
        s.shape = len(s)
        a,b = np.polyfit(s,diffs,1)

        lin_fit = a*s+b

        pylab.plot(s, diffs, 'g.', label='Real Differences')
        pylab.plot(s[ransac_data['inliers']], diffs[ransac_data['inliers']], 'r.', label='RANSAC Differences')
      #  pylab.plot(s, lin_fit, 'b.')

        #pylab.plot(secArray[ransac_data['inliers']], offArray[ransac_data['inliers']], 'r.')
       # pylab.plot(secArray[ransac_data['inliers']], offArray[ransac_data['inliers']])
        #pylab.plot(secArray[ransac_data['inliers']], lin_fit[ransac_data['inliers']], 'g.')

      #  pylab.plot(secArray[ransac_data['inliers']], lin_fit[ransac_data['inliers']])

        #pylab.plot( secArray[ransac_data['inliers'],0], offArray[ransac_data['inliers'],0], 'bx', label='RANSAC data' )
        pylab.legend(loc=2)
    #alanvar com gambi
        pylab.figure(12)

        [time1, av1, err1] = allantest.Allan.allanDevMills(diffs[ransac_data['inliers']])

        pylab.xlabel(r'$\tau$ - sec')
        pylab.ylabel(r'$\sigma(\tau$)')
        pylab.title('Allan Standard Deviation')


        pylab.loglog(time1, av1, 'b^', time1, av1)
        pylab.errorbar(time1, av1,yerr=err1,fmt='k.' )

        pylab.legend(('ADEV points', 'ADEV'), loc=2)


        pylab.grid(True)

        #semGambi
        pylab.figure(14)

        for item in self.offsets:
            item = item - self.offsets[0]

        diffs = diff(self.offsets)

        diffs = np.asarray(diffs)

        offArray = np.asarray(self.offsets)
        secArray = np.asarray(self.seconds)

        s = secArray[1:,]
        offArray.shape = (len(offArray),1)

        diffs.shape = (len(diffs), 1)

        s.shape = (len(s),1)


        all_data = numpy.hstack( (s,diffs) )

        #n - the minimum number of data required to fit the model
        #k - the number of iterations performed by the algorithm
        #t - a threshold value for determining when a datum fits a model
        #d - the number of close data values required to assert that a model fits well to data

        ransac_fit, ransac_data = ransac(all_data,model,20, 222, 0.2, 10, debug=1,return_all=True)
        diffs.shape = len(diffs)
        s.shape = len(s)
        a,b = np.polyfit(s,diffs,1)

        lin_fit = a*s+b

        pylab.plot(s, diffs, 'g.', label='Real Differences')
        pylab.plot(s[ransac_data['inliers']], diffs[ransac_data['inliers']], 'r.', label='RANSAC Differences')
        #  pylab.plot(s, lin_fit, 'b.')

        #pylab.plot(secArray[ransac_data['inliers']], offArray[ransac_data['inliers']], 'r.')
        # pylab.plot(secArray[ransac_data['inliers']], offArray[ransac_data['inliers']])
        #pylab.plot(secArray[ransac_data['inliers']], lin_fit[ransac_data['inliers']], 'g.')

        #  pylab.plot(secArray[ransac_data['inliers']], lin_fit[ransac_data['inliers']])

        #pylab.plot( secArray[ransac_data['inliers'],0], offArray[ransac_data['inliers'],0], 'bx', label='RANSAC data' )
        pylab.legend(loc=2)

        #alanvar sem gambi
        pylab.figure(15)

        [time1, av1, err1] = allantest.Allan.allanDevMills(diffs[ransac_data['inliers']])

        pylab.xlabel(r'$\tau$ - sec')
        pylab.ylabel(r'$\sigma(\tau$)')
        pylab.title('Allan Standard Deviation')


        pylab.loglog(time1, av1, 'b^', time1, av1)
        pylab.errorbar(time1, av1,yerr=err1,fmt='k.' )

        pylab.legend(('ADEV points', 'ADEV'), loc=2)


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