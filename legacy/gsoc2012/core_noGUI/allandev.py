#!/usr/bin/env python

"""

allandev.py: This module is responsible for the Allan Deviation Calculations

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
from math import *
import numpy as np


class AllanDev():

    def __init__(self):

        self.av = [0]
        self.timeS = [0]
        self.error = [0]

    def allanDevMills(self, values):

    ##########
    # Allan Deviation Calculation Routine adapted from David Mills Matlab sub-routine
    ##########

        timeInterval = []
        aDev = []
        error = []
        N = len(values)

        y1 = np.asarray(values)
        d=32
        i=0
        while(len(y1) >=10 ):
            u = diff(y1)/d
            v = diff(u)
            temp = sqrt(mean(v * v)/2)
            aDev.append(temp)
            timeInterval.append(d)
            y1 = y1[::2]
            temp2 = 1/sqrt(2*(((float)(N)/(pow(2,i)))-1))
            temp2 *= aDev[i]
            error.append(temp2)
            i=i+1
            d=d*2


        return timeInterval,aDev,error




    def allanDev(self,values, tau0):

    ##########
    # Allan Deviation Calculation Routine adapted from the R-Project package allanvar
    ##########

        N = len(values) # Number of data availables
        tau = tau0 # sampling time
        n = ceil((float)((N-1))/2)
        p = floor ((float)(log10(n))/log10(2)) #Number of clusters
        self.av = zeros(p+1)
        self.timeS = zeros(p+1)
        self.error = zeros(p+1)

        print ("Calculating Allan Deviation...")
        # Minimal cluster size is 1 and max is 2^p
        # in time would be 1*tau and max time would be (2^p)*tau
        for i in range((int)(p)):

            omega = zeros(floor((float)(N)/(pow(2,i)))) #floor(N/(2^i)) is the number of the cluster
            T = (pow(2,i))*tau

            l = 1
            k = 1
            #Perfome the average values
            while (k < floor((float)(N)/(pow(2,i)))):



                val = np.asarray(values[(int)(l):(int)((l+((pow(2,i))-1)))])
                tempSum = scipy.sum(val)

                omega[k] = (float)(tempSum)/(pow(2,i))
                l += (pow(2,i))
                k += 1

            sumvalue = 0

            #Perfom the difference of the average values
            for k in range(1,(len(omega)-1)):

                sumvalue += pow((omega[k+1]-omega[k]),2)


                #Compute the final step for Allan Deviation estimation

            self.av[i+1] = sqrt((float)(sumvalue)/(2*(len(omega)-1))) #i+1 because i starts at 0 (2^0 = 1)
            self.timeS [i+1] = T #i+1 because i starts at 0 (2^0 = 1)

            #Equation for error AV estimation
            #See Papoulis (1991) for further information
            self.error[i+1] = 1/sqrt(2*(((float)(N)/(pow(2,i)))-1))
            self.error[i+1] *= self.av[i+1]

        return self.timeS, self.av,self.error


    def allanDevn(self,values, tau0):

        N = len(values) # Number of data availables
        tau = tau0 # sampling time
        n = ceil((N-1)/2)


        self.av = zeros(n)
        self.timeS = zeros(n)
        error= zeros(n)


        print ("Calculating...")
        # Minimal cluster size is 1 and max is 2^p
        # in time would be 1*tau and max time would be (2^p)*tau
        for i in range(1,n):

            omega = zeros(floor(N/i)) #floor(N/(2^i)) is the number of the cluster
            T = i*tau

            l = 1
            k = 1
            #Perfome the average values
            while (k < floor(N/i)):



                val = values[(int)(l):(int)(l+(i-1))]
                tempSum = scipy.sum(val)
                print k, floor(N/i)

                omega[k] = (tempSum/i)
                l += i
                k += 1

            sumvalue = 0

            #Perfome the difference of the average values
            for k in range(1,(len(omega)-1)):

                sumvalue += pow((omega[k+1]-omega[k]),2)


                #Compute the final step for Allan Variance estimation
            self.av[i] = sumvalue/(2*(len(omega)-1)) #i+1 because i starts at 0 (2^0 = 1)
            self.timeS[i] = T #i+1 because i starts at 0 (2^0 = 1)

            #Equation for error AV estimation
            #See Papoulis (1991) for further information
            error[i] = 1/sqrt(2*((N/i)-1))

        return self.timeS, self.av,self.error