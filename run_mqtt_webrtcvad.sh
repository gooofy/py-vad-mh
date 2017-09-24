#!/bin/sh

while true ; do
   cd $HOME/projects/ai/ts2/py-vad-mh
   date >vad.log
   ./mqtt_webrtcvad >>vad.log 2>&1
done

