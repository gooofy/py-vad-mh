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
import scipy
import os
import ConfigParser
from os.path import expanduser
import array

from pulseclient import PARecorder

import VAD

FRAMES_PER_BUFFER = 16000
        
STATE_IDLE     = 0
STATE_SPEECH1  = 1
STATE_SPEECH2  = 2
STATE_SILENCE1 = 3
STATE_SILENCE2 = 4

RING_BUF_ENTRIES = 5 * 180 # 5 minutes max

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

try:
    recordfn  = config.get("audio", "recorddir")
except ConfigParser.NoOptionError:
    recordfn = None

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

rec = PARecorder (source, 16000, volume)

#
# main
#

rec.start_recording()
print "Recording..."

cnt = 0
avg_intensity = 0.0

state = STATE_IDLE

while True:

    samples = rec.get_samples(FRAMES_PER_BUFFER)

    print "%d samples, %5.1f s" % (len(samples)/2, float(len(samples)/2) / 16000.0)


    buf = array.array('B', samples).tostring()

    #l, buf  = recorder.record()
    ring_buffer[ring_cur] = numpy.fromstring(buf, dtype=numpy.int16)
    #ring_buffer[ring_cur] = buf

    #res =  ltsd.compute(audio)
    vad, avg_intensity =  VAD.moattar_homayounpour(ring_buffer[ring_cur], avg_intensity, cnt)

    print ring_cur, vad, avg_intensity
    
    if state == STATE_IDLE:
        if vad:
            state = STATE_SPEECH1
        else:
            audio_start = ring_cur
            audio_num   = 0

    elif state == STATE_SPEECH1:
        if vad: 
            print "*** SPEECH DETECTED at frame %3d ***" % audio_start
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

            while True:
                audiofn = "audio_%03d.wav" % audio_cur
                audio_cur += 1
                if not os.path.isfile(audiofn):
                    break

            print "*** END OF SPEECH at frame %3d (num: %5d, audiofn: %s) ***" % (ring_cur, audio_num, audiofn)

            wf = wave.open(audiofn, 'wb')
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.setnframes(audio_num * FRAMES_PER_BUFFER)

            audio = []
            for i in range(audio_num):
                audio.extend(ring_buffer[(audio_start + i) % RING_BUF_ENTRIES])

            packed_audio = struct.pack('%sh' % len(audio), *audio)
            wf.writeframes(packed_audio)

            wf.close()


    cnt       += 1
    audio_num += 1
    ring_cur   = (ring_cur + 1) % RING_BUF_ENTRIES


