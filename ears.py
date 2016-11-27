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
import traceback
from setproctitle import setproctitle

from pulseclient import PARecorder

import VAD

import zmq
import json
import logging

PROC_TITLE = 'hal_ears'

logging.basicConfig(level=logging.DEBUG)

setproctitle (PROC_TITLE)

SAMPLE_RATE       = 16000
FRAMES_PER_BUFFER = 16000 / 4

NUM_FRAMES_PRE    = 4

STATE_IDLE     = 0
STATE_SPEECH1  = 1
STATE_SPEECH2  = 2
STATE_SILENCE1 = 3
STATE_SILENCE2 = 4
STATE_SILENCE3 = 5
STATE_SILENCE4 = 6

RING_BUF_ENTRIES = 5 * 180 # 5 minutes max

def _comm (zmq_socket, cmd, arg):

    # logging.debug("_comm: %s %s" % (cmd, arg))

    res = None

    try:

        rq = json.dumps ([cmd, arg])

        #print "Sending request %s" % rq
        zmq_socket.send (rq)

        #  Get the reply.
        message = zmq_socket.recv()
        res = json.loads(message)
    except:

        logging.error("_comm: EXCEPTION.")
        traceback.print_exc()

        pass

    return res

def _comm_getty (cmd, arg):

    global zmq_socket_getty

    return _comm(zmq_socket_getty, cmd, arg)


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
configfn  = home_path + "/.halrc"

config = ConfigParser.RawConfigParser()

config.read(configfn)

source    = config.get("ears", "source")
volume    = int(config.get("ears", "volume"))

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

#
# pulseaudio recorder
#

rec = PARecorder (source, SAMPLE_RATE, volume)

logging.debug ('PARecorder initialized.')

#
# zmq connections
#

host_getty  = config.get('zmq', 'host_getty')
port_getty  = config.get('zmq', 'port_getty')
port_gettyp = config.get('zmq', 'port_gettyp')

zmq_context = zmq.Context()

logging.debug ("Subscribing to ZMQ getty broadcasts on %s:%s..." % (host_getty, port_gettyp))

zmq_socket_getty_sub = zmq_context.socket(zmq.SUB)
zmq_socket_getty_sub.connect ("tcp://%s:%s" % (host_getty, port_gettyp))

# messages we're interested in
zmq_socket_getty_sub.setsockopt(zmq.SUBSCRIBE, 'LISTEN')

logging.debug("subscribed.")

logging.debug ("Connecting to ZMQ getty server %s:%s..." % (host_getty, port_getty))
zmq_socket_getty = zmq_context.socket(zmq.REQ)
zmq_socket_getty.connect ("tcp://%s:%s" % (host_getty, port_getty))

logging.debug("conntected.")

logging.debug("sending EARS_BOOT...")

ears_enabled = _comm_getty ('EARS_BOOT', False)[0]

logging.debug("sending EARS_BOOT done.")

#
# main
#

rec.start_recording(FRAMES_PER_BUFFER)

cnt = 0
avg_intensity = 0.0

state = STATE_IDLE

def send_audio (slot, finalize):

    global ring_buffer

    slot = slot % RING_BUF_ENTRIES

    if ring_buffer[slot] is None:
        return

    logging.debug ("RECAUDIO slot=%d, finalize=%s" % (slot, finalize))

    if finalize:
        _comm_getty ("RECFINAL", ','.join(["%d" % sample for sample in ring_buffer[slot]]))
    else:
        _comm_getty ("RECAUDIO", ','.join(["%d" % sample for sample in ring_buffer[slot]]))

while True:

    logging.debug ("recording...")

    samples = rec.get_samples()

    logging.debug("%d samples, %5.2f s" % (len(samples), float(len(samples)) / float(SAMPLE_RATE)))

    # good time to recv broadcast messages
    try:
        msg = zmq_socket_getty_sub.recv(zmq.DONTWAIT)
        cmd, data = msg.split(' ', 1)
        data = json.loads(data)
        logging.debug("received broadcast message: cmd=%s, data=%s" % (cmd, repr(data)))

        if cmd == 'LISTEN':
            ears_enabled = data[0]

    except zmq.error.Again:
        pass

    if not ears_enabled:
        continue

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

    elif state == STATE_SPEECH1:
        if vad: 
            logging.debug ("*** SPEECH DETECTED at frame %3d ***" % audio_start)

            for i in range(audio_start - NUM_FRAMES_PRE, ring_cur+1):
                send_audio (i, False)

            state = STATE_SPEECH2
        else:
            state = STATE_IDLE
    elif state == STATE_SPEECH2:
        send_audio (ring_cur, False)
        if not vad:
            state = STATE_SILENCE1
    elif state == STATE_SILENCE1:
        send_audio (ring_cur, False)
        if vad:
            state = STATE_SPEECH2
        else:
            state = STATE_SILENCE2
    elif state == STATE_SILENCE2:
        send_audio (ring_cur, False)
        if vad:
            state = STATE_SPEECH2
        else:
            state = STATE_SILENCE3
    elif state == STATE_SILENCE3:
        send_audio (ring_cur, False)
        if vad:
            state = STATE_SPEECH2
        else:
            state = STATE_SILENCE4
    elif state == STATE_SILENCE4:
        if vad:
            state = STATE_SPEECH2
            send_audio (ring_cur, False)
        else:
            state = STATE_IDLE
            send_audio (ring_cur, True)

            logging.info("*** END OF SPEECH at frame %3d ***" % (ring_cur))

    cnt       += 1
    ring_cur   = (ring_cur + 1) % RING_BUF_ENTRIES

