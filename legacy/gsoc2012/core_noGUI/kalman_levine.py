import numpy
import pylab
import time
import math
from numpy import *
from math import *
from scipy import *

class kalman_levine():

    def __init__(self):
        self.xE = mat([[0.],[0.]])
        self.xV = mat([[0.],[0.]])
        self.epsT = 0.5
        self.epsO = 0.1
        self.I = mat([[1.,0.],[0.,1.]])

        self.estimateds = []

        self.z = mat([[1.],[0.]])

        self.estimateds.append(self.xE[0,0])
        self.estimateds.append(self.xE[0,0])


    def filter(self, input):

        diffs = diff(self.estimateds)

        diffsS = diffs*diffs

        mean_diffs = mean(diffsS)

        self.eps0 = sqrt(mean_diffs)

        self.xV = ((self.epsT*self.epsT)/(self.epsT*self.epsT+self.epsO*self.epsO))*self.xE\
                  + ((self.epsO*self.epsO)/(self.epsT*self.epsT+self.epsO*self.epsO))*input

        self.xE = (1-self.I)*self.xV + self.I*(self.z*input)

        self.estimateds.append(self.xE[0,0])


if __name__ == "__main__":

    kl = kalman_levine()

    inp = 1

    kl.filter(1)

    print kl.xE

    kl.filter(1)

    print kl.xE

    kl.filter(1)

    print kl.xE

    kl.filter(1)

    print kl.xE

    kl.filter(1)

    print kl.xE

    kl.filter(1)

    print kl.xE

    kl.filter(1)

    print kl.xE