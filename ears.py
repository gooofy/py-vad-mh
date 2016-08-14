#!/usr/bin/env python
# -*- coding: utf-8 -*- 

#
# Copyright 2013, 2014, 2016 Guenter Bartsch
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
# 
# You should have received a copy of the GNU Lesser General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

#
# based on :
# https://mattze96.safe-ws.de/blog/?p=640
#

import StringIO
import wave

import ctypes
import sys
import struct
import numpy
import os
import ConfigParser
from os.path import expanduser
import array
from time import time

from pulseclient import PARecorder

import VAD

import zmq
import json
import logging

ENABLE_LOCAL_WAVDUMP = False

logging.basicConfig(level=logging.DEBUG)

SAMPLE_RATE       = 16000
FRAMES_PER_BUFFER = 16000 / 2

NUM_FRAMES_PRE    = 1
NUM_FRAMES_POST   = 0

STATE_IDLE     = 0
STATE_SPEECH1  = 1
STATE_SPEECH2  = 2
STATE_SILENCE1 = 3
STATE_SILENCE2 = 4

RING_BUF_ENTRIES = 5 * 180 # 5 minutes max

def _comm (cmd, arg):

    global zmq_socket

    logging.debug("_comm: %s %s" % (cmd, arg))

    res = None

    try:

        rq = json.dumps ([cmd, arg])

        #print "Sending request %s" % rq
        zmq_socket.send (rq)

        #  Get the reply.
        message = zmq_socket.recv()
        res = json.loads(message)
    except:

        logging.error("tts_comm: EXCEPTION.")
        traceback.print_exc()

        pass

    return res

#
# init
#

reload(sys)
sys.setdefaultencoding('utf-8')
sys.stdout = os.fdopen(sys.stdout.fileno(), 'w', 0)

#
# load config, set up global variables
#

home_path = expanduser("~")
configfn  = home_path + "/.airc"

config = ConfigParser.RawConfigParser()

config.read(configfn)

source    = config.get("audio", "source")
volume    = int(config.get("audio", "volume"))

logging.debug ('HAL 9000 ears application started. Audio source: %s' % source)

#
# ring_buffer
#

ring_buffer    = []
for i in range(RING_BUF_ENTRIES):
    ring_buffer.append(None)

ring_cur    = 0
audio_cur   = 0
audio_start = 0
audio_num   = 0

#
# pulseaudio recorder
#

rec = PARecorder (source, SAMPLE_RATE, volume)

logging.debug ('PARecorder initialized.')

#
# zmq connection to asr server
#

asr_server = config.get("audio", "asr_server")
asr_port   = int(config.get("audio", "asr_port"))

zmq_context = zmq.Context()
logging.debug ("Connecting to ZMQ ASR server %s:%s..." % (asr_server, asr_port))
zmq_socket = zmq_context.socket(zmq.REQ)
zmq_socket.connect ("tcp://%s:%s" % (asr_server, asr_port))

logging.debug("conntected.")

#
# main
#

rec.start_recording(FRAMES_PER_BUFFER)

cnt = 0
avg_intensity = 0.0

state = STATE_IDLE

while True:

    logging.debug ("recording...")

    samples = rec.get_samples()

    logging.debug("%d samples, %5.1f s" % (len(samples), float(len(samples)) / float(SAMPLE_RATE)))

    #  buf = array.array('B', samples).tostring()

    #  logging.debug("len(samples)=%d, len(buf)=%d" % (len(samples), len(buf)))

    #  ring_buffer[ring_cur] = numpy.fromstring(buf, dtype=numpy.int16)
    ring_buffer[ring_cur] = samples

    logging.debug("VAD...")

    start_time = time()

    vad, avg_intensity =  VAD.moattar_homayounpour(ring_buffer[ring_cur], avg_intensity, cnt)

    end_time = time()

    logging.debug("VAD: ring_cur=%d, vad=%s, avg_intensity=%f, delay=%f" % (ring_cur, vad, avg_intensity, end_time - start_time))

     
    if state == STATE_IDLE:
        if vad:
            state = STATE_SPEECH1
        else:
            audio_start = ring_cur
            audio_num   = 0

    elif state == STATE_SPEECH1:
        if vad: 
            logging.debug ("*** SPEECH DETECTED at frame %3d ***" % audio_start)
            state = STATE_SPEECH2
        else:
            state = STATE_IDLE
    elif state == STATE_SPEECH2:
        if not vad:
            state = STATE_SILENCE1
    elif state == STATE_SILENCE1:
        if vad:
            state = STATE_SPEECH2
        else:
            state = STATE_SILENCE2
    elif state == STATE_SILENCE2:
        if vad:
            state = STATE_SPEECH2
        else:
            state = STATE_IDLE

            logging.info("*** END OF SPEECH at frame %3d (num: %5d) ***" % (ring_cur, audio_num))

            audio = []
            for i in range(audio_num + NUM_FRAMES_PRE + NUM_FRAMES_POST):
                audio.extend(ring_buffer[(audio_start + i - NUM_FRAMES_PRE) % RING_BUF_ENTRIES])

            # print type(audio), type(audio[0]), repr(audio)

            _comm ("REC", ','.join(["%d" % sample for sample in audio]))

            if ENABLE_LOCAL_WAVDUMP:

                while True:
                    audiofn = "audio_%03d.wav" % audio_cur
                    audio_cur += 1
                    if not os.path.isfile(audiofn):
                        break

                wf = wave.open(audiofn, 'wb')
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(SAMPLE_RATE)
                wf.setnframes(audio_num * FRAMES_PER_BUFFER)

                packed_audio = struct.pack('%sh' % len(audio), *audio)
                wf.writeframes(packed_audio)

                wf.close()
                logger.info("%s written." % audiofn)


    cnt       += 1
    audio_num += 1
    ring_cur   = (ring_cur + 1) % RING_BUF_ENTRIES

