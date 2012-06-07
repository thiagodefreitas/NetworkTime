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

from math import *


class plotSpace(FigureCanvas):

    def __init__(self):
        super(plotSpace, self).__init__(Figure())

        self.subplot = self.figure.add_subplot(111)
        self.subplot.hold(True)

    def update_plot(self, type, off, sec, av, error, timeS, tickCorrect):

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
            self.subplot.set_xlabel(r'$\tau$')
            self.subplot.set_ylabel(r'$\sigma(\tau$)')
            self.subplot.set_title('Allan Standard Deviation')
            plot2 = self.subplot.loglog(timeS, av, 'b^', timeS, av)
            plot1 = self.subplot.errorbar(timeS, av,yerr=error,fmt='k.', animated=True )
            self.subplot.grid()
            self.subplot.legend(('ADEV points', 'ADEV'))

            self.draw()

        elif(type==3):
            self.subplot.set_title("Histogram of the Offsets")
            self.subplot.hist(off)
            self.subplot.grid(True)
            self.draw()


    def save_plot(self, nametoSave):
        self.print_figure(nametoSave)