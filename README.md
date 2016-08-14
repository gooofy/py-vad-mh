Python app listening for voice activity on a microphone then sends over recorded WAV data to ASR server via zeromq.

Right now the most useful (and re-usable) part of this project is my cython port of the VAD (voice activity datection) algorithm implementation from Shriphani Palakodety found here:

https://github.com/shriphani/Listener

the algorithm implemented originates from a paper by Moattar and Homayounpour. My cython port is fast enough for real-time operation on a Raspberry Pi 3.

