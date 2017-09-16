#!/usr/bin/env python
# -*- coding: utf-8 -*- 

# based on: http://freshfoo.com/blog/pulseaudio_monitoring

from ctypes import POINTER, c_ubyte, c_void_p, c_ulong, cast, c_int16, c_uint16, c_float, c_int, byref, cdll

# https://github.com/Valodim/python-pulseaudio
from pulseaudio.lib_pulseaudio import *

import threading
import logging

import numpy as np

class PARecorder(object):

    def __init__(self, source_name, rate, volume):
        self.source_name = source_name
        self.rate        = rate
        self.volume      = volume

        # Wrap callback methods in appropriate ctypefunc instances so
        # that the Pulseaudio C API can call them
        self._context_notify_cb = pa_context_notify_cb_t(self.context_notify_cb)
        self._source_info_cb    = pa_source_info_cb_t(self.source_info_cb)
        self._stream_read_cb    = pa_stream_request_cb_t(self.stream_read_cb)
        self._null_cb           = pa_context_success_cb_t(null_cb)

        # lock/cond for buffers

        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock) 

    def start_recording(self, frames_per_buffer):

        logging.debug("start_recording...")

        self._frames_per_buffer = frames_per_buffer
        self._buffers           = []
        self._cur_buf_cnt       = 0

        self._buffers.append(np.empty(self._frames_per_buffer, dtype=np.int16))

        self._mainloop = pa_threaded_mainloop_new()
        _mainloop_api  = pa_threaded_mainloop_get_api(self._mainloop)
        self._context  = pa_context_new(_mainloop_api, 'HAL 9000 Ears')

        pa_context_set_state_callback(self._context, self._context_notify_cb, None)
        pa_context_connect(self._context, None, 0, None)

        pa_threaded_mainloop_start(self._mainloop)

    def stop_recording(self):

        logging.debug("stop_recording...")

        pa_threaded_mainloop_lock(self._mainloop)
        pa_context_disconnect(self._context)
        pa_context_unref(self._context)
        pa_threaded_mainloop_unlock(self._mainloop)

        pa_threaded_mainloop_stop(self._mainloop)
        pa_threaded_mainloop_free(self._mainloop)

        return self._samples
        

    def context_notify_cb(self, context, _):
        state = pa_context_get_state(context)

        if state == PA_CONTEXT_READY:
            logging.debug("Pulseaudio connection ready...")
            o = pa_context_get_source_info_list(context, self._source_info_cb, None)
            pa_operation_unref(o)

        elif state == PA_CONTEXT_FAILED :
            logging.error("Connection failed")

        elif state == PA_CONTEXT_TERMINATED:
            logging.info("Connection terminated")

    def source_info_cb(self, context, source_info_p, _, __):
        if not source_info_p:
            return

        logging.debug("source_info_cb...")

        source_info = source_info_p.contents

        logging.debug('index       : %d' % source_info.index)
        logging.debug('name        : %s' % source_info.name)
        logging.debug('description : %s' % source_info.description)

        if self.source_name in source_info.description:

            #
            # set volume first
            #

            cvol = pa_cvolume()
            cvol.channels = 1
            cvol.values[0] = (self.volume * PA_VOLUME_NORM) / 100

            operation = pa_context_set_source_volume_by_index (self._context, source_info.index, cvol, self._null_cb, None)
            pa_operation_unref(operation)

            logging.info('recording from %s' % source_info.name)

            samplespec = pa_sample_spec()
            samplespec.channels = 1
            samplespec.format = PA_SAMPLE_S16LE
            samplespec.rate = self.rate

            pa_stream = pa_stream_new(context, "hal_ears", samplespec, None)
            pa_stream_set_read_callback(pa_stream,
                                        self._stream_read_cb,
                                        source_info.index)

            # flags = PA_STREAM_NOFLAGS
            flags = PA_STREAM_ADJUST_LATENCY
            
            # buffer_attr = None
            buffer_attr = pa_buffer_attr(-1, -1, -1, -1, fragsize=self._frames_per_buffer*2)

            pa_stream_connect_record(pa_stream,
                                     source_info.name,
                                     buffer_attr,
                                     flags)

    def stream_read_cb(self, stream, length, index_incr):
        data = c_void_p()
        pa_stream_peek(stream, data, c_ulong(length))
        data = cast(data, POINTER(c_ubyte))

        self._lock.acquire()

        for i in xrange(length/2):

            sample = data[i*2] + 256 * data[i*2+1]

            self._buffers[len(self._buffers)-1][self._cur_buf_cnt] = sample
            self._cur_buf_cnt += 1 

            # buffer full?
            if self._cur_buf_cnt >= self._frames_per_buffer:

                self._buffers.append(np.empty(self._frames_per_buffer, dtype=np.int16))
                self._cur_buf_cnt = 0

                self._cond.notifyAll()


        self._lock.release()

        pa_stream_drop(stream)


    def get_samples(self):

        self._lock.acquire()

        buf = None
        while len(self._buffers) < 2:
            self._cond.wait()

        buf = self._buffers.pop(0)

        self._lock.release()

        return buf

def null_cb(a=None, b=None, c=None, d=None):
    return


class PAPlayer:

    def __init__(self, name, channels=1, rate=16000):
        self.name     = name
        self.channels = channels
        self.rate     = rate
        self.pa       = cdll.LoadLibrary('libpulse-simple.so.0')

    def play(self, buf, len):

        ss = pa_sample_spec()

        ss.rate     = self.rate
        ss.channels = self.channels
        ss.format   = PA_SAMPLE_S16LE

        error = c_int(0)
    
        s = self.pa.pa_simple_new(
            None,                # Default server.
            self.name,           # Application's name.
            PA_STREAM_PLAYBACK,  # Stream for playback.
            None,                # Default device.
            'playback',          # Stream's description.
            byref(ss),           # Sample format.
            None,                # Default channel map.
            None,                # Default buffering attributes.
            byref(error)         # Ignore error code.
        )
        if not s:
            raise Exception('Could not create pulse audio stream: {0}!'.format(pa.strerror(byref(error))))

        if self.pa.pa_simple_write(s, buf, len, error):
            raise Exception('Could not play file!')
        
        # Waiting for all sent data to finish playing.
        if self.pa.pa_simple_drain(s, error):
            raise Exception('Could not simple drain!')
        
        # Freeing resources and closing connection.
        self.pa.pa_simple_free(s)

