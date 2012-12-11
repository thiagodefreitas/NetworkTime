import numpy
import pylab
import time
import math
from numpy import *
from math import *
from scipy import *

class Kalman():

    def __init__(self):
        self.R = 1e2*eye(1)
        self.P = 1e6*eye(2)
        self.Q = 1e2*eye(2)

        self.I = mat([[1.,0.],[0.,1.]])

        self.tau = 32.0

        self.xE = mat([[0.],[0.]])

        self.H = mat([[1.,0.]])
        self.F = mat([[1.,self.tau], [0.,1.]])
        self.G = mat([[1.,self.tau/2], [0.,1.]])

    def filter(self, input):

        e = input - self.H*self.xE
        S = self.H*self.P*transpose(self.H) + self.R
        W = self.P*transpose(self.H)*numpy.linalg.inv(S)
        self.xE = self.xE + W*e
        self.P = self.P - W*S*transpose(W)


        self.xE = self.F * self.xE
        self.P = self.F*self.P*transpose(self.F) + self.G*self.Q*transpose(self.G)*self.tau