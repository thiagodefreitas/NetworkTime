#!/usr/bin/env python


"""

estimators.py: This module is responsible for generating NTP request and to analyze its packets

"""

__author__ = "Thiago de Freitas Oliveira Araujo"
__copyright__ = "Copyright 2012, Google"
__credits__ = ["Judah Levine", "Harlan Stenn", "Antonio Lima"]
__license__ = "GPL"
__version__ = "1.0"
__maintainer__ = "Thiago de Freitas"
__email__ = "thiago.oliveira@ee.ufcg.edu.br"
__status__ = "Prototype"

import ntplib
from time import *
import time
import logging
import kalman_class
import threading
from numpy import *
from math import *
from scipy import *
import os
import numpy
import kalman_levine
import savitzky
import pylab
import kalman_2nd

import itertools
"""

Log Definitions.

"""
logger = logging.getLogger("estimators")
hdlr = logging.FileHandler("estimators.log")
formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
hdlr.setFormatter(formatter)
logger.addHandler(hdlr)
logger.setLevel(logging.DEBUG)


class NTPEstimators():
    """Class to Save Offsets and Current Time to Text Files for Further Processing"""

    def __init__(self, server, online, offFile, cTimeFile, dTimeFile,recTimeFile, refTimeFile, txTimeFile, kfFile, mavFile):
        self.server = server
        self.offFileName = offFile
        self.cTimeFileName = cTimeFile
        self.dTimeFileName = dTimeFile
        self.recTimeFileName = recTimeFile
        self.refTimeFileName = refTimeFile
        self.txTimeFileName = txTimeFile
        self.kfFileName = kfFile
        self.mavFileName = mavFile
        self.realTime = "realtime.txt"
        self.thread_update = None
        self.response = None
        self.ntpClient = ntplib.NTPClient()
        self.fileOffsets = open("on" + self.offFileName, "w")
        self.cTimeFile = open("on" + self.cTimeFileName, "w")
        self.dTimeFile = open("on" + self.dTimeFileName, "w")
        self.realTimeFile = open("on" + self.realTime, "w")
        self.refTimeFile = open("on" + self.refTimeFileName, "w")
        self.txTimeFile = open("on" + self.txTimeFileName, "w")
        self.recTimeFile = open("on" + self.recTimeFileName, "w")
        self.kfFile2 = open("on" + self.kfFileName, "w")
        self.kfFile = open(self.kfFileName, "w")
        self.mavFile = open("on" + self.mavFileName, "w")
        self.online = online

        self.file_off = open("off_kalman_levine.txt", "w")

        self.file_off2 = open("off_kalman2.txt", "w")

        self.kf = kalman_class.Kalman()
        self.kl = kalman_levine.kalman_levine()
        self.kf2 = kalman_2nd.Kalman2()

        self.sg = savitzky.savitzky_golay(window_size=39, order=5)
        self.estimateds = zeros(39)
        self.sg_index = 0

        self.sgK = 1 # this variable controls if savitzky is applied to the Kalman Filter
        self.sgL = 1 # this variable controls if savitzky is applied to the Levines Kalman Filter
        self.sgK2 = 1

        self.kf_off = mat([[0.],[0.]])
        self.kf2_off = mat([[0.],[0.]])
        self.kl_off = mat([[0.],[0.]])

        self.init_kalman = 1

        self.delta_t1 = 0.
        self.delta_t4 = 0.
        self.delta_t12 = 0.
        self.delta_t42 = 0.

        self.delta_t1av = 0.
        self.delta_t4av = 0.

        if(self.online):
            self.response = self.ntpClient.request(self.server, version=4)

            self.t1_kalman = (float)(self.response.orig_time)
            self.t4_kalman = (float)(self.response.dest_time)

            self.t1_kalman_average = (float)(self.response.orig_time)
            self.t4_kalman_average = (float)(self.response.dest_time)

            self.t1_av = (float)(self.response.orig_time)
            self.t4_av = (float)(self.response.dest_time)

        else:

            self.orig_time = open(self.cTimeFileName).readlines()
            self.dest_time = open(self.dTimeFileName).readlines()
            self.tx_time = open(self.txTimeFileName).readlines()
            self.recv_time = open(self.recTimeFileName).readlines()
            self.off_rec = open(self.offFileName).readlines()


            for a,b,c, d, e in itertools.izip(self.orig_time, self.dest_time, self.tx_time, self.recv_time, self.off_rec):

                self.orig_time[self.orig_time.index(a)] = (float)(a.strip())
                self.dest_time[self.dest_time.index(b)] = (float)(b.strip())
                self.tx_time[self.tx_time.index(c)] = (float)(c.strip())
                self.recv_time[self.recv_time.index(d)] = (float)(d.strip())
                self.off_rec[self.off_rec.index(e)] = (float)(e.strip())

            self.off_recT = zeros(len(self.off_rec))
            self.off_recT2 = zeros(len(self.off_rec))
            self.off_recL = zeros(len(self.off_rec))

            self.t1_kalman = (self.orig_time[0])
            self.t4_kalman = (self.dest_time[0])

            self.t1_kalman2 = (self.orig_time[0])
            self.t4_kalman2 = (self.dest_time[0])

            self.t1_kl = (self.orig_time[0])
            self.t4_kl = (self.dest_time[0])

            self.t1_kalman_average = (self.orig_time[0])
            self.t4_kalman_average = (self.dest_time[0])

            self.t1_av = (self.orig_time[0])
            self.t4_av = (self.dest_time[0])


        self.t1_old = self.t1_kalman
        self.t4_old = self.t4_kalman

        self.enable_kalman = 0
        self.enable_ntpdate = 0

        self.actual_calculated_offset = 0.

        logger.info("Init Funcion Concluded")


        self.past_offs = [0,0,0,0,0]
        self.offs_moving = [0,0,0,0,0]

        self.new_off = 0

        self.start_time = time.time()

        self.update_once = 1

    def __del__(self):
        #logger.info("Destructor Initialized")
        self.fileOffsets.flush()
        self.cTimeFile.flush()
        self.fileOffsets.close()
        self.cTimeFile.close()

    def get_responses(self):

        try:

            if(self.online):
                self.thread_update = threading.Timer(32.0, self.get_responses)
                self.thread_update.start()

                if (self.enable_ntpdate):
                    os.system("sudo /home/thiago/ntdate.sh")
                    time.sleep(8)


                self.response = self.ntpClient.request(self.server, version=4)


                self.delta_t1 = (float)(self.response.orig_time) - self.t1_kalman
                self.delta_t4 = (float)(self.response.dest_time) - self.t4_kalman

                ####
                self.delta_t1av = (float)(self.response.orig_time) - self.t1_av
                self.delta_t4av = (float)(self.response.dest_time) - self.t4_av

                self.t1_av += (self.delta_t1av) + self.offs_moving[0]
                self.t4_av += (self.delta_t4av) + self.offs_moving[0]

                ####

                ######## Moving Average
                self.offs_moving[4] = self.offs_moving[3]
                self.offs_moving[3] = self.offs_moving[2]
                self.offs_moving[2] = self.offs_moving[1]
                self.offs_moving[1] = self.offs_moving[0]
                self.offs_moving[0] = (((float)(self.response.recv_time)-(float)(self.t1_av))+(float)(self.response.tx_time)-(float)(self.t4_av))/2

                print "Moving Average Offset.", self.offs_moving[0]

                WINDOW = 5
                extended_data = numpy.hstack([[self.offs_moving[0]] * (WINDOW- 1), self.offs_moving])
                weightings = numpy.repeat(1.0, WINDOW) / WINDOW
                mean_off = numpy.convolve(extended_data, weightings)[WINDOW-1:-(WINDOW-1)]
                ###########


                self.t1_kalman += (self.delta_t1) + self.kf_off[0,0]
                self.t4_kalman += (self.delta_t4) + self.kf_off[0,0]

                self.kf_off[0,0] = (((float)(self.response.recv_time)-(float)(self.t1_kalman))+(float)(self.response.tx_time)-(float)(self.t4_kalman))/2
                print "Offset from Kalman. Before filter.", self.kf_off[0,0]


                self.make_logs()

                self.update_kalman()

                differs_old = diff(self.past_offs)
                mean_old = mean(differs_old)

                self.past_offs[4] = self.past_offs[3]
                self.past_offs[3] = self.past_offs[2]
                self.past_offs[2] = self.past_offs[1]
                self.past_offs[1] = self.past_offs[0]
                self.past_offs[0] = self.kf_off[0,0]

                differs = diff(self.past_offs)
                mean_upd = mean(differs)

                mean_spd = mean_upd - mean_old
                print "Mean", mean_spd

                elapsed_time = time.time()-self.start_time
                print "elapsed time:", elapsed_time

                if(elapsed_time>900):
                    self.start_time = time.time()
                    self.kf_off[0,0] = mean_old/5
                    print "passed on elapsed!!"

                elif(abs(mean_spd) > 0.006):
                    self.kf_off[0,0] =  mean_old/5

                #update moving average
                self.offs_moving[0] = mean_off[4]
                #########

                self.t1_old = (float)(self.response.orig_time)
                self.t4_old = (float)(self.response.dest_time)

            else:


                for orig_time, dest_time, tx_time, recv_time, off_rec in itertools.izip(self.orig_time[1:], self.dest_time[1:], self.tx_time[1:], self.recv_time[1:], self.off_rec[1:]):

                    self.delta_t1 = (float)(orig_time) - self.t1_kalman
                    self.delta_t4 = (float)(dest_time) - self.t4_kalman

                    self.delta_t12 = (float)(orig_time) - self.t1_kalman2
                    self.delta_t42 = (float)(dest_time) - self.t4_kalman2
                    ####
                    self.delta_t1av = (float)(orig_time) - self.t1_kl
                    self.delta_t4av = (float)(dest_time) - self.t4_kl
                    print "DELTAS", self.delta_t1av, self.delta_t4av, self.delta_t1, self.delta_t4
                    ####
                    self.t1_kalman += (self.delta_t1) + self.kf_off[0,0]
                    self.t4_kalman += (self.delta_t4) + self.kf_off[0,0]

                    self.t1_kalman2 += (self.delta_t12) + self.kf2_off[0,0]
                    self.t4_kalman2 += (self.delta_t42) + self.kf2_off[0,0]


                    self.t1_kl += (self.delta_t1av) + self.kl_off[0,0]
                    self.t4_kl += (self.delta_t4av) + self.kl_off[0,0]

                    self.kf_off[0,0] = (((float)(recv_time)-(float)(self.t1_kalman))+(float)(tx_time)-(float)(self.t4_kalman))/2
                    print "Offset from Kalman. Before filter.", self.kf_off[0,0]

                    self.kf2_off[0,0] = (((float)(recv_time)-(float)(self.t1_kalman2))+(float)(tx_time)-(float)(self.t4_kalman2))/2
                    print "Offset from second order Kalman. Before filter.", self.kf2_off[0,0]

                    self.kl_off[0,0] = (((float)(recv_time)-(float)(self.t1_kl))+(float)(tx_time)-(float)(self.t4_kl))/2

                    print "Offset from Kalman Levine. Before filter.", self.kl_off[0,0]


                    self.off_recT[self.dest_time.index(dest_time)] = self.kf_off[0,0]
                    self.off_recT2[self.dest_time.index(dest_time)] = self.kf2_off[0,0]
                    self.off_recL[self.dest_time.index(dest_time)] = self.kl_off[0,0]

                    if(self.sg_index>=38):

                        self.off_recT = self.sg.filter(self.off_recT)
                        self.off_recT2 = self.sg.filter(self.off_recT2)
                        self.off_recL = self.sg.filter(self.off_recL)
                    #TODO: generalize

                    self.sg_index+=1

                    if(self.sgK):
                        self.kf_off[0,0] = self.off_recT[self.dest_time.index(dest_time)]
                    if(self.sgK2):
                        self.kf2_off[0,0] = self.off_recT2[self.dest_time.index(dest_time)]
                    if(self.sgL):
                        self.kl_off[0,0] = self.off_recL[self.dest_time.index(dest_time)]

                    print "NTP Offset", off_rec
                    self.fileOffsets.write("%s\n" % (float)(off_rec))

                    self.make_logs()

                    self.update_kalman()


                    self.kl.filter(self.kl_off[0,0])
                    self.kl_off = self.kl.xE
                    print "Kalman Levine generated estimator", self.kl_off

                    self.kf2.filter(self.kf2_off[0,0])
                    self.kf2_off = self.kf2.xE2
                    print "Kalman Levine generated estimator", self.kf2_off

                    self.t1_old = (float)(orig_time)
                    self.t4_old = (float)(dest_time)



        except Exception,e:
            print ("Exception?", e)
            self.kf_off[0,0] = 0.
            self.update_kalman()
            logger.error("Error when trying to connect to Server %s", self.server)
            raise
        finally:
            return



    def make_logs(self):



        if(self.online):

            self.fileOffsets.write("%s\n" % self.response.offset)
            self.cTimeFile.write("%s\n" % self.response.orig_time)
            self.dTimeFile.write("%s\n" % self.response.dest_time)
            self.recTimeFile.write("%s\n" % self.response.recv_time)
            self.refTimeFile.write("%s\n" % self.response.ref_time)
            self.txTimeFile.write("%s\n" % self.response.tx_time)
            self.kfFile.write("%s\n" % (float)(self.kf_off[0,0]))
            self.mavFile.write("%s\n" % (float)(self.offs_moving[0]))

            self.realTimeFile.write("%s\n" % (str)(time.time()))

            logger.info("Logged: [off, %s, time, %s]", self.response.offset, self.response.orig_time)

        self.file_off.write("%s\n" % (float)(self.kl_off[0,0]))
        self.file_off2.write("%s\n" % (float)(self.kf2_off[0,0]))
        self.kfFile.write("%s\n" % (float)(self.kf_off[0,0]))

    def update_kalman(self):
        if(self.online):
            print "NTP calculated estimator", self.response.offset
        self.kf.filter(self.kf_off[0,0])
        self.kf_off = self.kf.xE
        print "Kalman Filter generated estimator", self.kf_off

if __name__ == '__main__':

    try:
        estimatorTest = NTPEstimators("utcnist.colorado.edu", 0, "offsets_estimation.txt", "computeTime_estimation.txt", "serverTime_estimation.txt","recTime_estimation.txt" , "refTime_estimation.txt", "txTime_estimation.txt", "off_kalman.txt","off_mav.txt")
        if (estimatorTest.online):
            estimatorTest.thread_update = threading.Timer(32.0, estimatorTest.get_responses)
            estimatorTest.thread_update.start()
            while(True):
                print "Running Estimator"
                time.sleep(2)
        else:
            estimatorTest.get_responses()

            pylab.plot(estimatorTest.off_recT)

            pylab.show()

    except Exception, e:
        logger.error("The following exception was thrown %s", e)
        pass