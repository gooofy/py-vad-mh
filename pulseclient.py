#!/usr/bin/env python
# -*- coding: utf-8 -*- 

# based on: http://freshfoo.com/blog/pulseaudio_monitoring

from ctypes import POINTER, c_ubyte, c_void_p, c_ulong, cast, c_int16, c_uint16, c_float, c_int, byref, cdll

# https://github.com/Valodim/python-pulseaudio
from pulseaudio.lib_pulseaudio import *

import threading

VERBOSE = True

class PARecorder(object):

    def __init__(self, source_name, rate, volume):
        self.source_name = source_name
        self.rate        = rate
        self.volume      = volume

        # Wrap callback methods in appropriate ctypefunc instances so
        # that the Pulseaudio C API can call them
        self._context_notify_cb = pa_context_notify_cb_t(self.context_notify_cb)
        self._source_info_cb = pa_source_info_cb_t(self.source_info_cb)
        self._stream_read_cb = pa_stream_request_cb_t(self.stream_read_cb)
        self._null_cb = pa_context_success_cb_t(null_cb)

        # lock/cond for samples

        self.lock = threading.Lock()
        self.cond = threading.Condition(self.lock) 

    def start_recording(self):

        if VERBOSE:
            print "start_recording..."

        self._samples = []

        self._mainloop = pa_threaded_mainloop_new()
        _mainloop_api = pa_threaded_mainloop_get_api(self._mainloop)
        self._context = pa_context_new(_mainloop_api, 'peak_demo')
        pa_context_set_state_callback(self._context, self._context_notify_cb, None)
        pa_context_connect(self._context, None, 0, None)
        pa_threaded_mainloop_start(self._mainloop)

    def stop_recording(self):

        if VERBOSE:
            print "stop_recording..."

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
            if VERBOSE:
                print "Pulseaudio connection ready..."
            o = pa_context_get_source_info_list(context, self._source_info_cb, None)
            pa_operation_unref(o)

        elif state == PA_CONTEXT_FAILED :
            if VERBOSE:
                print "Connection failed"

        elif state == PA_CONTEXT_TERMINATED:
            if VERBOSE:
                print "Connection terminated"

    def source_info_cb(self, context, source_info_p, _, __):
        if VERBOSE:
            print "source_info_cb..."

        if not source_info_p:
            return

        source_info = source_info_p.contents

        if VERBOSE:
            print 'index:', source_info.index
            print 'name:', source_info.name
            print 'description:', source_info.description

        if self.source_name in source_info.description:

            #
            # set volume first
            #

            cvol = pa_cvolume()
            cvol.channels = 1
            cvol.values[0] = (self.volume * PA_VOLUME_NORM) / 100

            operation = pa_context_set_source_volume_by_index (self._context, source_info.index, cvol, self._null_cb, None)
            pa_operation_unref(operation)

            print
            print 'recording from', source_info.name
            print

            samplespec = pa_sample_spec()
            samplespec.channels = 1
            samplespec.format = PA_SAMPLE_S16LE
            samplespec.rate = self.rate

            pa_stream = pa_stream_new(context, "netsphinx", samplespec, None)
            pa_stream_set_read_callback(pa_stream,
                                        self._stream_read_cb,
                                        source_info.index)
            pa_stream_connect_record(pa_stream,
                                     source_info.name,
                                     None,
                                     PA_STREAM_NOFLAGS)

    def stream_read_cb(self, stream, length, index_incr):
        data = c_void_p()
        pa_stream_peek(stream, data, c_ulong(length))
        data = cast(data, POINTER(c_ubyte))

        self.lock.acquire()

        for i in xrange(length):
            self._samples.append(data[i])

        self.cond.notifyAll()

        self.lock.release()

        pa_stream_drop(stream)


    def get_samples(self, num_samples):

        self.lock.acquire()

        buf = []
        for i in range(num_samples):

            while len(self._samples) == 0:
                self.cond.wait()

            buf.append(self._samples.pop(0))

        self.lock.release()

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

