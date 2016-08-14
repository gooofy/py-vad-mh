#!/usr/bin/env python
# encoding: utf-8
# cython: profile=False
# filename: VAD.pyx

# Author: Shriphani Palakodety
# spalakod@cs.cmu.edu

# Cython port 2016 by G. Bartsch
from libcpp cimport bool

from numpy.fft import *

import numpy as np
cimport numpy as np

MH_FRAME_DURATION     = 10 #frame length in milliseconds for Moattar & Homayounpour
MH_SAMPLES_PER_SECOND = 16000
MH_SAMPLES_PER_FRAME  = int(MH_SAMPLES_PER_SECOND * (MH_FRAME_DURATION / 1000.0))

DTYPE = np.int16
ctypedef np.int16_t DTYPE_t

DTYPEC = np.complex128
ctypedef np.complex128_t DTYPEC_t

DTYPEF = np.float64
ctypedef np.float64_t DTYPEF_t

def chunk_frames_indices(np.ndarray[DTYPE_t, ndim=1] samples, int samples_per_frame):
    '''
    Args:
        - samples: 16 bit values representing a sampled point.

    Returns:
        - an array of <FRAME_DURATION> length chunks
    '''
    return zip(
        range(0, len(samples), samples_per_frame),
        range(samples_per_frame, len(samples), samples_per_frame)
    )

cdef real_imaginary_freq_domain(np.ndarray[DTYPE_t, ndim=1] samples):
    '''
    Apply fft on the samples and return the real and imaginary
    parts in separate 
    '''

    cdef np.ndarray[DTYPEC_t, ndim=1] freq_domain = fft(samples)

    cdef int l = len(freq_domain)

    cdef np.ndarray[DTYPEF_t, ndim=1] freq_domain_real = np.empty(l, DTYPEF)
    cdef np.ndarray[DTYPEF_t, ndim=1] freq_domain_imag = np.empty(l, DTYPEF)

    cdef int i

    for i in range(l):
        freq_domain_real[i] = abs(freq_domain[i].real)
        freq_domain_imag[i] = abs(freq_domain[i].imag)

    return freq_domain_real, freq_domain_imag

# cdef int find_first(float item, np.ndarray[DTYPEF_t, ndim=1] vec):
#     """return the index of the first occurence of item in vec"""
# 
#     cdef int i
# 
#     for i in range(len(vec)):
#         if item == vec[i]:
#             return i
#     return -1


cdef float get_dominant_freq(np.ndarray[DTYPEF_t, ndim=1] real_freq_domain_part, np.ndarray[DTYPEF_t, ndim=1] imag_freq_domain_part):
    '''Returns the dominant frequency'''

    cdef float max_real     = 0.0
    cdef float max_imag     = 0.0
    cdef int   max_real_idx = 0
    cdef int   max_imag_idx = 0

    cdef int i

    for i in range (len(real_freq_domain_part)):

        if real_freq_domain_part[i] > max_real:
            max_real     = real_freq_domain_part[i]
            max_real_idx = i

        if imag_freq_domain_part[i] > max_imag:
            max_imag     = imag_freq_domain_part[i]
            max_imag_idx = i

    cdef float dominant_freq = 0

    if max_real > max_imag:
        dominant_freq = abs(fftfreq(len(real_freq_domain_part), d=(1.0/44100.0))[max_real_idx])
    else:
        dominant_freq = abs(fftfreq(len(imag_freq_domain_part), d=(1.0/44100.0))[max_imag_idx])


    # cdef float max_real = max(real_freq_domain_part)
    # cdef float max_imag = max(imag_freq_domain_part)

    # cdef float dominant_freq = 0

    # if max_real > max_imag:
    #     dominant_freq = abs(fftfreq(len(real_freq_domain_part), d=(1.0/44100.0))[find_first(max_real, real_freq_domain_part)])
    # else:
    #     dominant_freq = abs(fftfreq(len(imag_freq_domain_part), d=(1.0/44100.0))[find_first(max_imag, imag_freq_domain_part)])

    return dominant_freq

cdef np.ndarray[DTYPEF_t, ndim=1] get_freq_domain_magnitudes(np.ndarray[DTYPEF_t, ndim=1] real_part, np.ndarray[DTYPEF_t, ndim=1] imaginary_part):
    '''Magnitudes of the real-imag frequencies'''

    cdef np.ndarray[DTYPEF_t, ndim=1] freq_magnitudes = np.sqrt(real_part**2 + imaginary_part**2)

    return freq_magnitudes

cdef float get_sfm(np.ndarray[DTYPEF_t, ndim=1] frequencies):
    return 10 * np.log10(geometric_mean(frequencies) / np.mean(frequencies))

cdef float geometric_mean(np.ndarray[DTYPEF_t, ndim=1] a):
    return np.exp(np.log(a).mean())

cdef float get_sample_intensity(np.ndarray[DTYPE_t, ndim=1] samples):
    return 20.8 * np.log10(np.sqrt(sum([float(x) ** 2 for x in samples])/float(len(samples))))

def locateInArray(list1, list2):
    x = 0
    y = 0
    for x in xrange(len(list1)):
        if list1[x] == list2[0]:
            counter = 0
            for y in xrange(len(list2)):
                try:
                    if list1[x+y] != list2[y]:
                        break
                    else:
                        counter += 1
                except IndexError:
                    return -1
            if counter == len(list2):
                return x
    return -1

    

def moattar_homayounpour(np.ndarray[DTYPE_t, ndim=1] abs_samples, float average_intensity, int instances):
    '''
    Args:
        - samples : array of audio samples (int16)
        - average_intensity : former average_intensity set by the user (we supply an updated value)
        - instances : number of times this VAD was run was previously
    '''

    # set primary thresholds for energy, frequency and SFM
    # these values were determined using experiements by the authors
    # themselves
    cdef float energy_prim_thresh = 40
    cdef float freq_prim_thresh   = 185
    cdef float sfm_prim_thresh    = 5
    
    cdef int   n_frames = len(abs_samples)

    #print abs_samples

    #compute the intensity
    cdef float intensity = get_sample_intensity(abs_samples)

    #frame attribute arrays
    frame_max_frequencies  = []  #holds the dominant frequency for each frame
    frame_SFMs             = []  #holds the spectral flatness measure for every frame
    frame_voiced           = []  #tells us if a frame contains silence or speech

    #attributes for the entire sampled signal
    cdef float min_energy        = 0
    cdef float min_dominant_freq = 0
    cdef float min_sfm           = 0

    cdef float energy_thresh, dominant_freq_thresh, sfm_thresh

    #check for the 30 frame mark
    cdef bint  thirty_frame_mark = False

    cdef int   i, frame_start, frame_end, counter

    cdef np.ndarray[DTYPE_t, ndim=1]  frame
    cdef float                        frame_energy, dominant_freq, frame_SFM
    cdef np.ndarray[DTYPEF_t, ndim=1] freq_domain_real 
    cdef np.ndarray[DTYPEF_t, ndim=1] freq_domain_imag 
    cdef np.ndarray[DTYPEF_t, ndim=1] freq_magnitudes

    for i, frame_bounds in enumerate(chunk_frames_indices(abs_samples, MH_SAMPLES_PER_FRAME)):

        frame_start = frame_bounds[0]
        frame_end = frame_bounds[1]

        # marks if 30 frames have been sampled
        if i >= 30:
            thirty_frame_mark = True

        frame = abs_samples[frame_start:frame_end]

        # compute frame energy
        frame_energy = sum([float(x)**2 for x in frame])

        freq_domain_real, freq_domain_imag = real_imaginary_freq_domain(frame)
        freq_magnitudes                    = get_freq_domain_magnitudes(freq_domain_real, freq_domain_imag)
        dominant_freq                      = get_dominant_freq(freq_domain_real, freq_domain_imag)
        frame_SFM                          = get_sfm(freq_magnitudes)

        #now, append these attributes to the frame attribute arrays created previously
        frame_max_frequencies.append(dominant_freq)
        frame_SFMs.append(frame_SFM)

        #the first 30 frames are used to set min-energy, min-frequency and min-SFM
        if not thirty_frame_mark and not i:
            min_energy        = frame_energy
            min_dominant_freq = dominant_freq
            min_sfm           = frame_SFM
            
        elif not thirty_frame_mark:
            min_energy        = min(min_energy, frame_energy)
            min_dominant_freq = min(dominant_freq, min_dominant_freq)
            min_sfm           = min(frame_SFM, min_sfm)

        #once we compute the min values, we compute the thresholds for each of the frame attributes
        energy_thresh        = energy_prim_thresh * np.log10(min_energy)
        dominant_freq_thresh = freq_prim_thresh
        sfm_thresh           = sfm_prim_thresh

        counter = 0

        if (frame_energy - min_energy) > energy_thresh:
            counter += 1
        if (dominant_freq - min_dominant_freq) > dominant_freq_thresh:
            counter += 1
        if (frame_SFM - min_sfm) > sfm_thresh:
            counter += 1

        if counter > 1:     #this means that the current frame is not silence.
            frame_voiced.append(1)
        else:
            frame_voiced.append(0)
            min_energy = ((frame_voiced.count(0) * min_energy) + frame_energy)/(frame_voiced.count(0) + 1)

        #now update the energy threshold
        energy_thresh = energy_prim_thresh * np.log10(min_energy)

    #once the frame attributes are obtained, a final check is performed to determine speech.
    #at least 5 consecutive frames are needed for speech.

    instances += 1  #a new instance has been processed
    old_average_intensity = average_intensity   
    average_intensity = ((old_average_intensity * (instances-1)) + intensity) / float(instances)  #update average intensity

    if locateInArray(frame_voiced, [1, 1, 1, 1, 1]) >= 0 and intensity > old_average_intensity:
        return (True, average_intensity)

    return (False, average_intensity)
    

