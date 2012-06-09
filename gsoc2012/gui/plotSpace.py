#!/usr/bin/env python

"""

plotSpace.py: This module plots is responsible for the plots inside the Gui

"""

__author__ = "Thiago de Freitas Oliveira Araujo"
__copyright__ = "Copyright 2012, Google"
__credits__ = ["Judah Levine", "Harlan Stenn", "Antonio Lima"]
__license__ = "GPL"
__version__ = "1.0"
__maintainer__ = "Thiago de Freitas"
__email__ = "thiago.oliveira@ee.ufcg.edu.br"
__status__ = "Prototype"

from matplotlib.figure import Figure
from matplotlib.backends.backend_qt4agg import FigureCanvasQTAgg as FigureCanvas
from time import ctime

import numpy as np

from math import *


class plotSpace(FigureCanvas):

    def __init__(self):
        super(plotSpace, self).__init__(Figure())

        self.subplot = self.figure.add_subplot(111)
        self.subplot.hold(True)

    def plotMinusLeastSquares(self,type, off, sec, av, error, timeS, tickCorrect):

        self.subplot.clear()

        self.subplot.set_xlabel('Hours(h)')
        self.subplot.set_ylabel('Residuals(ms)')

        a,b = np.polyfit(sec,off,1)
        secArray = np.asarray(sec)
        offArray = np.asarray(off)

        self.subplot.plot(secArray, offArray-(a*secArray+b), '--k')

        xMin = sec[0]
        xMax = sec[len(sec)-1]

        xMin = (int)((floor)(xMin))

        xMax = (int)((floor)(xMax))

        self.subplot.set_xlim([xMin,xMax])

        toPlot = []
        toPlotTime = []

        for i in range(len(sec)):
            if i%4 == 0:
                ct = ctime(sec[i])
                ct = ct.split(' ')
                if '' in ct:
                    ct.remove('')
                ct = ct[3].split(':')
                toPlot.append(ct[0])
                toPlotTime.append(sec[i])



        self.subplot.set_title("Offsets Subtracted by a Least Squares Fit")

        self.subplot.grid()

        if tickCorrect:
            self.subplot.set_xticks(toPlotTime)
            self.subplot.set_xticklabels(toPlot)

        self.draw()

    def plotAllanPPM(self, type, off, sec, av, error, timeS, tickCorrect):

        self.subplot.clear()

        self.subplot.set_xlabel(r'$\tau$ - sec')
        self.subplot.set_ylabel(r'$\sigma(\tau$) - PPM')
        self.subplot.set_title('Allan Standard Deviation')
        plot2 = self.subplot.loglog(timeS, np.asarray(av)*1e6, 'b^', timeS, np.asarray(av) *1e6)
        plot1 = self.subplot.errorbar(timeS, np.asarray(av)*1e6,yerr=np.asarray(error)*1e6,fmt='k.' )
        self.subplot.grid()
        self.subplot.legend(('ADEV points', 'ADEV'))

        self.draw()

    def update_plot(self, type, off, sec, av, error, timeS, tickCorrect):

        self.subplot.clear()
        if(type==1):

            self.subplot.set_xlabel('Hours(h)')
            self.subplot.set_ylabel('Offsets(ms)')

            self.subplot.plot(sec,off)

            xMin = sec[0]
            xMax = sec[len(sec)-1]

            xMin = (int)((floor)(xMin))

            xMax = (int)((floor)(xMax))

            self.subplot.set_xlim([xMin,xMax])

            toPlot = []
            toPlotTime = []

            for i in range(len(sec)):
                if i%4 == 0:
                    ct = ctime(sec[i])
                    ct = ct.split(' ')
                    if '' in ct:
                        ct.remove('')
                    ct = ct[3].split(':')
                    toPlot.append(ct[0])
                    toPlotTime.append(sec[i])



            self.subplot.set_title("Offsets Generated from a NTP trial run")

            self.subplot.grid()

            if tickCorrect:
                self.subplot.set_xticks(toPlotTime)
                self.subplot.set_xticklabels(toPlot)

            self.draw()

        elif(type==2):


            self.subplot.set_xlabel(r'$\tau$ - sec')
            self.subplot.set_ylabel(r'$\sigma(\tau$) - ms')
            self.subplot.set_title('Allan Standard Deviation')
            plot2 = self.subplot.loglog(timeS, av, 'b^', timeS, av)
            plot1 = self.subplot.errorbar(timeS, av,yerr=error,fmt='k.', animated=True )
            self.subplot.grid()
            self.subplot.legend(('ADEV points', 'ADEV'))

            self.draw()

        elif(type==3):

            self.subplot.set_title("Normalized Histogram of the Offsets")
            self.subplot.hist(off, 50, normed=True, facecolor='green', alpha=0.75)
            self.subplot.set_xlabel('Offsets')
            self.subplot.set_ylabel('Probability')
            self.subplot.set_title(r'$\mathrm{Histogram\ of\ the\ Offsets}$')

            self.subplot.grid(True)
            self.draw()


    def save_plot(self, nametoSave):
        self.print_figure(nametoSave)