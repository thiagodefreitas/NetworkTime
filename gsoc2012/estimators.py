#!/usr/bin/env python


"""

estimators.py: This module is responsible for generating NTP request and to analyze its packets

"""

__author__ = "Thiago de Freitas Oliveira Araujo"
__copyright__ = "Copyright 2012, Google"
__credits__ = ["Judah Levine", "Harlan Stenn"]
__license__ = "GPL"
__version__ = "1.0"
__maintainer__ = "Thiago de Freitas"
__email__ = "thiago.oliveira@ee.ufcg.edu.br"
__status__ = "Prototype"

import ntplib
from time import *
import time
import logging


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

    def __init__(self, server, offFile, cTimeFile):

        self.server = server
        self.offFileName = offFile
        self.cTimeFileName = cTimeFile
        self.response = None
        self.ntpClient = ntplib.NTPClient()
        self.fileOffsets = open(self.offFileName,"w")
        self.cTimeFile = open(self.cTimeFileName,"w")

        logger.info("Init Funcion Concluded")

    def __del__(self):
        logger.info("Destructor Initialized")
        self.fileOffsets.flush()
        self.cTimeFile.flush()
        self.fileOffsets.close()
        self.cTimeFile.close()

    def get_responses(self):
        try:

            self.response = self.ntpClient.request(self.server, version=4)
            logger.info('Got Response from server %s', self.server)
            self.fileOffsets.write("%s\n" % self.response.offset)
            self.cTimeFile.write("%s\n" % self.response.orig_time)
	    logger.info("Logged: [off, %s, time, %s]", self.response.offset, self.response.orig_time)
        except:
            logger.error("Error when trying to connect to Server %s", self.server)
            raise
        finally:
            return

if __name__ == '__main__':

    estimatorTest = NTPEstimators("utcnist2.colorado.edu", "offsets_estimation.txt", "computeTime_estimation.txt")


    while(True):
        try:

            estimatorTest.get_responses()
            time.sleep(1024)

        except Exception, e:
            logger.error("The following exception was thrown %s", e)
            pass
