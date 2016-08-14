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

import sys
import numpy as np
import os
import logging
import pstats, cProfile

from time import time

import VAD

logging.basicConfig(level=logging.DEBUG)

# SAMPLE_RATE       = 16000
# FRAMES_PER_BUFFER = 16000 / 2

FRAMES_PER_BUFFER = 100000

#
# init
#

reload(sys)
sys.setdefaultencoding('utf-8')
sys.stdout = os.fdopen(sys.stdout.fileno(), 'w', 0)

#
# main
#

buf = np.random.randint(-1000,+1000,FRAMES_PER_BUFFER).astype(np.int16)

logging.debug("VAD...")

start_time = time()

cnt = 0
avg_intensity = 0.0

cProfile.runctx("vad, avg_intensity = VAD.moattar_homayounpour(buf, avg_intensity, cnt)", globals(), locals(), "Profile.prof")

end_time = time()

logging.debug("VAD: vad=%s, avg_intensity=%f, delay=%f" % (vad, avg_intensity, end_time - start_time))

s = pstats.Stats("Profile.prof")
s.strip_dirs().sort_stats("time").print_stats()


