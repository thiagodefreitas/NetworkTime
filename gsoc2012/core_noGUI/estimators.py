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

    def __init__(self, server, offFile, cTimeFile, dTimeFile,recTimeFile, refTimeFile, txTimeFile, kfFile, mavFile):
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
        self.fileOffsets = open(self.offFileName, "w")
        self.cTimeFile = open(self.cTimeFileName, "w")
        self.dTimeFile = open(self.dTimeFileName, "w")
        self.realTimeFile = open(self.realTime, "w")
        self.refTimeFile = open(self.refTimeFileName, "w")
        self.txTimeFile = open(self.txTimeFileName, "w")
        self.recTimeFile = open(self.recTimeFileName, "w")
        self.kfFile = open(self.kfFileName, "w")
        self.mavFile = open(self.mavFileName, "w")



        self.kf = kalman_class.Kalman()

        self.kf_off = mat([[0.],[0.]])

        self.init_kalman = 1

        self.delta_t1 = 0.
        self.delta_t4 = 0.
        self.delta_t1av = 0.
        self.delta_t4av = 0.

        self.response = self.ntpClient.request(self.server, version=4)

        self.t1_kalman = (float)(self.response.orig_time)
        self.t4_kalman = (float)(self.response.dest_time)

        self.t1_kalman_average = (float)(self.response.orig_time)
        self.t4_kalman_average = (float)(self.response.dest_time)

        self.t1_av = (float)(self.response.orig_time)
        self.t4_av = (float)(self.response.dest_time)

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
        logger.info("Destructor Initialized")
        self.fileOffsets.flush()
        self.cTimeFile.flush()
        self.fileOffsets.close()
        self.cTimeFile.close()

    def get_responses(self):
        self.thread_update = threading.Timer(32.0, self.get_responses)
        self.thread_update.start()

        try:

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

        except:
            self.kf_off[0,0] = 0.
            self.update_kalman()
            logger.error("Error when trying to connect to Server %s", self.server)
            raise
        finally:
            return

    def make_logs(self):

        logger.info('Got Response from server %s', self.server)

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

    def update_kalman(self):
        print "NTP calculated estimator", self.response.offset
        self.kf.filter(self.kf_off[0,0])
        self.kf_off = self.kf.xE
        print "Kalman Filter generated estimator", self.kf_off


if __name__ == '__main__':
    estimatorTest = NTPEstimators("utcnist.colorado.edu", "offsets_estimation.txt", "computeTime_estimation.txt", "serverTime_estimation.txt","recTime_estimation.txt" , "refTime_estimation.txt", "txTime_estimation.txt", "off_kalman.txt","off_mav.txt")
    estimatorTest.thread_update = threading.Timer(32.0, estimatorTest.get_responses)
    estimatorTest.thread_update.start()
    while(True):
        try:
            print "Running Estimator"
            time.sleep(2)

        except Exception, e:
            logger.error("The following exception was thrown %s", e)
            pass
