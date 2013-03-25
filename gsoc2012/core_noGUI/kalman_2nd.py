import numpy
import pylab
import time
import math
from numpy import *
from math import *
from scipy import *

class Kalman2():

    def __init__(self):
        self.R = 1e2*eye(1)
        self.P = 1e3*eye(3)
        self.Q = 0.01*eye(3)

        self.I = mat([[1.,0.],[0.,1.]])

        self.tau = 32.0

        self.xE2 = mat([[0.],[0.],[0.]])

        self.H = mat([[1.,0.,0.]])
        self.F = mat([[1.,self.tau, self.tau*self.tau/2], [0.,1.,self.tau], [0.,0.,1.]])
        self.G = mat([[1.,self.tau/2], [0.,1.], [0., 1.]])

        self.z = mat([[1.],[0.], [0.]])

    def filter(self, input):


        e = input - self.H*self.xE2

        S = self.H*self.P*transpose(self.H) + self.R

        W = self.P*transpose(self.H)*numpy.linalg.inv(S)

        self.xE2 = self.xE2 + W*e

        self.P = self.P - W*S*transpose(W)

        self.xE2 = self.F * self.xE2

        self.P = self.F*self.P*transpose(self.F) + self.Q #self.G*self.Q*transpose(self.G)*self.tau

if __name__ == "__main__":

    kf = Kalman2()

    for i in range(50):

        kf.filter(i)
        print "estimation"
        print kf.xE2
        print "done estimation"