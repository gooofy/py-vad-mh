VAD.so:		VAD.pyx
			python setup.py build_ext --inplace


clean:
			rm -f VAD.c VAD.so

