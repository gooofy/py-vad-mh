#!/usr/bin/env python
# -*- coding: utf-8 -*- 

#
# Copyright 2013, 2014, 2016 Guenter Bartsch
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

#
# simple benchmark app for VAD tuning
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

