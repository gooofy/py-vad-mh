from distutils.core import setup
from Cython.Build import cythonize

setup(
  name = 'Voice Activity Detection',
  ext_modules = cythonize("VAD.pyx"),
)
