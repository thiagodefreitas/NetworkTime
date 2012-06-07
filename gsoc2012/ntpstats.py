#!/usr/bin/env python

"""

ntpstats.py: Main Window for the Gui Version of the Program

"""

__author__ = "Thiago de Freitas Oliveira Araujo"
__copyright__ = "Copyright 2012, Google"
__credits__ = ["Judah Levine", "Harlan Stenn", "Antonio Lima"]
__license__ = "GPL"
__version__ = "1.0"
__maintainer__ = "Thiago de Freitas"
__email__ = "thiago.oliveira@ee.ufcg.edu.br"
__status__ = "Prototype"


import sys
import inspect
import os
import platform
import PySide
import matplotlib
import scipy
import time
from time import ctime


cmd_folder = os.path.realpath(os.path.abspath(os.path.split(inspect.getfile( inspect.currentframe() ))[0]))
if cmd_folder not in sys.path:
    sys.path.insert(0, cmd_folder)

os.environ['QT_API'] = 'pyside'

matplotlib.use('Qt4Agg')
from matplotlib.backends.backend_qt4agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure



import pylab
import gui.plotSpace as plotSpace

import core_noGUI.logProcessing as logProcessing
import core_noGUI.loopLoader as loopLoader
import core_noGUI.allanandPlots as Runner

from PySide import QtCore, QtGui
from PySide.QtGui  import (QApplication, QMainWindow, QWidget,
                          QGridLayout, QTabWidget, QPlainTextEdit,
                          QMenuBar, QMenu, QStatusBar, QAction,
                          QIcon, QFileDialog, QMessageBox, QFont)

__version__ = '1.0 Prototype'


from gui.ui_mainwindow import Ui_MainWindow



class MainWindow(QtGui.QMainWindow):
    def __init__(self, parent=None):
        QtGui.QMainWindow.__init__(self, parent)
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)
        self.connectActions()

        self.loopProcessor = loopLoader.loopLoader()
        self.logProcessor = logProcessing.logProcess()
        self.runProcessor = Runner.allanandPlots()

        self.filename  = None
        self.filetuple = None

        self.plot_spaceOff = plotSpace.plotSpace()
        self.plot_spaceAllan = plotSpace.plotSpace()
        self.plot_spaceHist = plotSpace.plotSpace()

        self.ui.plotSpace.addWidget(self.plot_spaceOff)
        self.ui.plotSpace_3.addWidget(self.plot_spaceAllan)
        self.ui.plotSpace_2.addWidget(self.plot_spaceHist)

        self.type = 0

        self.sizeOff = 0

        self.numberOFTicks = 0

        self.exceeds = 0



    def connectActions(self):
        self.ui.actionNtpStatus.connect(PySide.QtCore.SIGNAL("triggered()"), self.aboutBox)

        self.ui.actionLoopstats.connect(PySide.QtCore.SIGNAL("triggered()"), self.fileLoopstats)
        self.ui.actionLoadLopstats.connect(PySide.QtCore.SIGNAL("triggered()"), self.fileLoopstats)

        self.ui.actionLoadRun.connect(PySide.QtCore.SIGNAL("triggered()"), self.fileRun)
        self.ui.actionRun_File.connect(PySide.QtCore.SIGNAL("triggered()"), self.fileRun)

        self.ui.actionLoadLog.connect(PySide.QtCore.SIGNAL("triggered()"), self.fileLog)
        self.ui.actionLog_File.connect(PySide.QtCore.SIGNAL("triggered()"), self.fileLog)

        self.ui.actionPlot.connect(PySide.QtCore.SIGNAL("triggered()"), self.generatePlot)

        self.ui.actionSave.connect(PySide.QtCore.SIGNAL("triggered()"), self.plotSave)

        self.connect(self.ui.actionExit, QtCore.SIGNAL('triggered()'), self.close)

    def aboutBox(self):

        QMessageBox.about(self, "About NTPStats 2012",
            """<b>Google Summer of Code 2012.</b> v %s
            <p>Copyright &copy; 2012 Google and NTP.
            All rights reserved in accordance with
            GPL v2.
            <p>This programs plots the Allan Deviation and Offsets for\
             logs of NTP Runs.
             <p> Developed by Thiago de Freitas Oliveira Araujo
            <p>Python %s -  PySide version %s - Qt version %s on\
            %s""" % (__version__, platform.python_version(),\
                         PySide.__version__,  PySide.QtCore.__version__,
                         platform.system()))

    def closeEvent(self, event):

        reply = QtGui.QMessageBox.question(self, 'Leave NTPStats',
            "Are you sure to quit?", QtGui.QMessageBox.No |
                                     QtGui.QMessageBox.Yes, QtGui.QMessageBox.No)

        if reply == QtGui.QMessageBox.Yes:
            event.accept()
        else:
            event.ignore()

    def fileLoopstats(self):

        if self.ui.tabWidget.currentIndex():
            self.oktoLoad()
            return
        else:
            dir = (os.path.dirname(self.filename)
                   if self.filename is not None else ".")
            self.filetuple = QFileDialog.getOpenFileName(self,\
                "Open Loopstats File", dir,\
                "Data (*.dat *.txt)\nAll Files (*.*)")
            self.filename = self.filetuple[0]
            fname = self.filename

            if fname:
                self.loopProcessor.processLoopStats(fname)
                self.loadFile(fname)
                self.updateStatus('New Loopstats file opened.')
                [self.loopProcessor.timeS, self.loopProcessor.av, self.loopProcessor.error] = self.loopProcessor.Allan.allanDev(self.loopProcessor.offsets, 10)
                self.type = 1

                self.sizeOff = len(self.loopProcessor.offsets)
                if(self.sizeOff%84 != 0):
                    self.exceeds = self.sizeOff%84


                self.numberOFTicks = scipy.ceil((float)(self.sizeOff)/84)
                self.ui.spinBox.setRange(1,self.numberOFTicks)



    def fileRun(self):

        if self.ui.tabWidget.currentIndex():
            self.oktoLoad()
            return
        else:
            dir = (os.path.dirname(self.filename)
                   if self.filename is not None else ".")
            self.filetuple = QFileDialog.getOpenFileName(self,\
                "Open Generated Times File", dir,\
                "Data (*.dat *.txt)\nAll Files (*.*)")
            self.filename = self.filetuple[0]
            fname = self.filename

            dir = (os.path.dirname(self.filename)
                   if self.filename is not None else ".")
            self.filetuple = QFileDialog.getOpenFileName(self,\
                "Open Generated Offsets File", dir,\
                "Data (*.dat *.txt)\nAll Files (*.*)")
            self.filename = self.filetuple[0]
            fname2 = self.filename

            if fname:
                self.runProcessor.processOffsets(fname, fname2)
                self.loadFile(fname)
                self.updateStatus('New Run Statistics File opened.')
                [self.runProcessor.timeS, self.runProcessor.av, self.runProcessor.error] = self.runProcessor.Allan.allanDev(self.runProcessor.offsets, 10)
                self.type = 2
                self.sizeOff = len(self.runProcessor.offsets)
                if(self.sizeOff%84 != 0):
                    self.exceeds = self.sizeOff%84

                self.numberOFTicks = scipy.ceil((float)(self.sizeOff)/84)
                self.ui.spinBox.setRange(1,self.numberOFTicks)

    def fileLog(self):

        if self.ui.tabWidget.currentIndex():
            self.oktoLoad()
            return
        else:
            dir = (os.path.dirname(self.filename)
                   if self.filename is not None else ".")
            self.filetuple = QFileDialog.getOpenFileName(self,\
                "Open Log File", dir,\
                "Data (*.log)\nAll Files (*.*)")
            self.filename = self.filetuple[0]
            fname = self.filename

            if fname:
                self.logProcessor.processLog(fname)
                self.loadFile(fname)
                self.updateStatus('New Log file opened.')
                [self.logProcessor.timeS, self.logProcessor.av, self.logProcessor.error] = self.logProcessor.Allan.allanDev(self.logProcessor.offsets, 10)
                self.type = 3
                self.sizeOff = len(self.logProcessor.offsets)
                if(self.sizeOff%84 != 0):
                    self.exceeds = self.sizeOff%84
                self.numberOFTicks = scipy.ceil((float)(self.sizeOff)/84)
                self.ui.spinBox.setRange(1,self.numberOFTicks)


    def oktoPlot(self):

        reply = QMessageBox.warning(self,
            "Warning",
            '''\nPlotting is only possible at a Plot tab!''', QMessageBox.Ok)
        return True

    def oktoLoad(self):

        reply = QMessageBox.warning(self,
            "Warning",
            '''\nLoading is only possible at the Contents Tab!''', QMessageBox.Ok)
        return True

    def oktoSavePlot(self):

        reply = QMessageBox.warning(self,
            "Warning",
            '''\nPlot Save is only possible at a Plot tab!''', QMessageBox.Ok)
        return True

    def loadFile(self, fname=None):
        fl = open(fname)
        text = fl.read()
        self.ui.textEdit.setPlainText(text)


    def plotSave(self):

        if not (self.ui.tabWidget.currentIndex()):
            self.oktoSavePlot()
            return
        elif self.ui.tabWidget.currentIndex()==1:
            nameSave = self.ui.nametoSave.text()
            self.plot_spaceOff.save_plot(nameSave)

        elif self.ui.tabWidget.currentIndex()==2:
            nameSave = self.ui.nametoSave_2.text()
            self.plot_spaceAllan.save_plot(nameSave)

        elif self.ui.tabWidget.currentIndex()==3:
            nameSave = self.ui.nametoSave_3.text()
            self.plot_spaceHist.save_plot(nameSave)


    def updateStatus(self, message):

        if self.filename is not None:
            fileN = os.path.basename(self.filename)
            self.setWindowTitle(unicode("Statistics File - " +\
                                        fileN + "[*]") )
            self.statusBar().showMessage(message, 5000)


    def generatePlot(self):

        if not (self.ui.tabWidget.currentIndex()):
            self.oktoPlot()
            return

        elif self.ui.tabWidget.currentIndex()==1: #Offsets

            if(self.type == 1): # LOOPSTATS

                if self.ui.radioButton.isChecked():
                    if not self.exceeds:
                        range_min = (self.ui.spinBox.value()-1)*84
                        range_max = range_min + 84
                        self.plot_spaceOff.update_plot(1, self.loopProcessor.offsets[range_min:range_max], self.loopProcessor.seconds[range_min:range_max], av=None, error=None, timeS=None, tickCorrect=1)
                        smallText = "Initial Time:" + "\n" + ctime(self.loopProcessor.seconds[range_min]) + "\n" +\
                                    "Final Time:" + "\n" + ctime(self.loopProcessor.seconds[range_max])
                        self.ui.textEdit_2.setText(smallText)
                    else:

                        range_min = (self.ui.spinBox.value()-1)*84

                        range_max = (self.ui.spinBox.value()*84)

                        if(self.ui.spinBox.value() == self.numberOFTicks):
                            range_max = range_min + self.exceeds

                        self.plot_spaceOff.update_plot(1, self.loopProcessor.offsets[range_min:range_max], self.loopProcessor.seconds[range_min:range_max], av=None, error=None, timeS=None, tickCorrect=1)
                        smallText = "Initial Time:" + "\n" + ctime(self.loopProcessor.seconds[range_min]) + "\n" +\
                                    "Final Time:" + "\n" + ctime(self.loopProcessor.seconds[range_max-1])
                        self.ui.textEdit_2.setText(smallText)
                else:
                    self.plot_spaceOff.update_plot(1, self.loopProcessor.offsets, self.loopProcessor.seconds, av=None, error=None, timeS=None, tickCorrect=0)
                    smallText = "Initial Time:" + "\n" + ctime(self.loopProcessor.seconds[0]) + "\n" +\
                                "Final Time:" + "\n" + ctime(self.loopProcessor.seconds[-1])
                    self.ui.textEdit_2.setText(smallText)

            elif(self.type == 2): #RUN

                if self.ui.radioButton.isChecked():
                    if not self.exceeds:
                        range_min = (self.ui.spinBox.value()-1)*84
                        range_max = range_min + 84
                        self.plot_spaceOff.update_plot(1, self.runProcessor.offsets[range_min:range_max], self.runProcessor[range_min:range_max].seconds, av=None, error=None, timeS=None, tickCorrect=1)
                        smallText = "Initial Time:" + "\n" + ctime(self.runProcessor.seconds[range_min]) + "\n" +\
                                    "Final Time:" + "\n" + ctime(self.runProcessor.seconds[range_max])
                        self.ui.textEdit_2.setText(smallText)
                    else:

                        range_min = (self.ui.spinBox.value()-1)*84

                        range_max = (self.ui.spinBox.value()*84)

                        if(self.ui.spinBox.value() == self.numberOFTicks):
                            range_max = range_min + self.exceeds

                        self.plot_spaceOff.update_plot(1, self.runProcessor.offsets[range_min:range_max], self.runProcessor.seconds[range_min:range_max], av=None, error=None, timeS=None, tickCorrect=1)
                        smallText = "Initial Time:" + "\n" + ctime(self.runProcessor.seconds[range_min]) + "\n" +\
                                    "Final Time:" + "\n" + ctime(self.runProcessor.seconds[range_max-1])
                        self.ui.textEdit_2.setText(smallText)
                else:
                    self.plot_spaceOff.update_plot(1, self.runProcessor.offsets, self.runProcessor.seconds, av=None, error=None, timeS=None, tickCorrect=0)
                    smallText = "Initial Time:" + "\n" + ctime(self.runProcessor.seconds[0]) + "\n" +\
                                "Final Time:" + "\n" + ctime(self.runProcessor.seconds[-1])
                    self.ui.textEdit_2.setText(smallText)

            elif(self.type == 3): #LOG

                self.ui.textEdit_2.clear()

                if self.ui.radioButton.isChecked():
                    if not self.exceeds:
                        range_min = (self.ui.spinBox.value()-1)*84
                        range_max = range_min + 84
                        self.plot_spaceOff.update_plot(1, self.logProcessor.offsets[range_min:range_max], self.logProcessor.seconds[range_min:range_max], av=None, error=None, timeS=None, tickCorrect=1)
                        smallText = "Initial Time:" + "\n" + ctime(self.logProcessor.seconds[range_min]) + "\n" +\
                                    "Final Time:" + "\n" + ctime(self.logProcessor.seconds[range_max])
                        self.ui.textEdit_2.setText(smallText)
                    else:

                        range_min = (self.ui.spinBox.value()-1)*84

                        range_max = (self.ui.spinBox.value()*84)

                        if(self.ui.spinBox.value() == self.numberOFTicks):
                            range_max = range_min + self.exceeds

                        self.plot_spaceOff.update_plot(1, self.logProcessor.offsets[range_min:range_max], self.logProcessor.seconds[range_min:range_max], av=None, error=None, timeS=None, tickCorrect=1)
                        smallText = "Initial Time:" + "\n" + ctime(self.logProcessor.seconds[range_min]) + "\n" +\
                                    "Final Time:" + "\n" + ctime(self.logProcessor.seconds[range_max-1])
                        self.ui.textEdit_2.setText(smallText)
                else:
                    self.plot_spaceOff.update_plot(1, self.logProcessor.offsets, self.logProcessor.seconds, av=None, error=None, timeS=None, tickCorrect=0)
                    smallText = "Initial Time:" + "\n" + ctime(self.logProcessor.seconds[0]) + "\n" + \
                                "Final Time:" + "\n" + ctime(self.logProcessor.seconds[-1])
                    self.ui.textEdit_2.setText(smallText)




        elif self.ui.tabWidget.currentIndex()==2: # Allan Deviations

            if(self.type ==1): # LOOPSTATS
                self.plot_spaceAllan.update_plot(2, off=None, sec=None, av=self.loopProcessor.av, error=self.loopProcessor.error, timeS=self.loopProcessor.timeS, tickCorrect=0)
                smallText = 'tau' + "\t" + "Adev" + "\n"
                smallText += "-------------------------\n"
                for i in range(1,len(self.loopProcessor.timeS)):
                    smallText += str(self.loopProcessor.timeS[i]) + "\t" + str(self.loopProcessor.av[i])  + "\n"
                self.ui.textEdit_3.setText(smallText)

            elif(self.type == 2): #RUN
                self.plot_spaceAllan.update_plot(2, off=None, sec=None, av=self.runProcessor.av, error=self.runProcessor.error, timeS=self.runProcessor.timeS, tickCorrect=0)
                smallText = 'tau' + "\t" + "Adev" + "\n"
                smallText += "-------------------------\n"
                for i in range(1,len(self.runProcessor.timeS)):
                    smallText += str(self.runProcessor.timeS[i]) + "\t" + str(self.runProcessor.av[i])  + "\n"
                self.ui.textEdit_3.setText(smallText)

            elif(self.type==3): # LOG
                self.plot_spaceAllan.update_plot(2, off=None, sec=None, av=self.logProcessor.av, error=self.logProcessor.error, timeS=self.logProcessor.timeS, tickCorrect=0)
                smallText = 'tau' + "\t" + "Adev" + "\n"
                smallText += "-------------------------\n"
                for i in range(1,len(self.logProcessor.timeS)):
                    smallText += str(self.logProcessor.timeS[i]) + "\t" + str(self.logProcessor.av[i])  + "\n"
                self.ui.textEdit_3.setText(smallText)

        elif self.ui.tabWidget.currentIndex()==3: #Histograms

            if(self.type == 1): # LOOPSTATS
                self.plot_spaceHist.update_plot(3, self.loopProcessor.offsets, sec=None, av=None, error=None, timeS=None, tickCorrect=0)

            elif(self.type == 2): #RUN
                self.plot_spaceHist.update_plot(3, self.runProcessor.offsets, sec=None, av=None, error=None, timeS=None, tickCorrect=0)

            elif(self.type == 3): # LOG
                self.plot_spaceHist.update_plot(3, self.logProcessor.offsets, sec=None, av=None, error=None, timeS=None, tickCorrect=0)


if __name__ == "__main__":
    app = QtGui.QApplication(sys.argv)
    mainW = MainWindow()
    mainW.show()


    execution = app.exec_()

    sys.exit(execution)