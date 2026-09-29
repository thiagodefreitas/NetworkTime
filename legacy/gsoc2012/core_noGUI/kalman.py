import numpy
import pylab
import time
import math
from numpy import *
from math import *
from scipy import *



R = 500*eye(1)
P = 1e6*eye(2)
H = mat([[1.,0.]])
I = mat([[1.,0.],[0.,1.]])
tau = 1024

xE0 = []

measurements = open("offsets.txt").readlines()

for m in measurements:
	measurements[measurements.index(m)] = (float)(m.strip("\n"))

print measurements

xE = mat([[0.],[0.]])
#F = mat([[1.,tau, tau*tau/2], [0.,1.,tau], [0.,0.,1.]])
F = mat([[1.,tau], [0.,1.]])

for i in range(len(measurements)):
	
    e = measurements[i] - H*xE
    S = H*P*transpose(H) + R
    W = P*transpose(H)*numpy.linalg.inv(S)    
    xE = xE + W*e
    P = P - W*S*transpose(W)


    xE = F * xE    
    P = F*P*transpose(F)

    xE0.append(xE[0,0])

print xE

#tserver = zeros(len(measurements))
#tclient = zeros(len(measurements))#

#for i in range(len(measurements)):
#    tserver[i] = 16*i
#    if (i>=1):
#    	tclient[i] = tclient[i-1]+16+xE0[i-1]#
#	xE0[i]+=(tserver[i]-tclient[i])

pylab.plot(xE0)
#pylab.plot(tserver-tclient)
pylab.grid()

pylab.show()
