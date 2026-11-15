"""Reuse the installed PyTorch OpenMP runtime on macOS when available.

Tree-model wheels reference @rpath/libomp.dylib. Loading the same runtime
already shipped with PyTorch avoids requiring a second OpenMP installation.
No libraries are downloaded or system paths modified.
"""
import ctypes
import sys
from functools import lru_cache
from importlib.util import find_spec
from pathlib import Path


@lru_cache(maxsize=1)
def prepare_openmp():
    if sys.platform != 'darwin':
        return None
    spec = find_spec('torch')
    if spec is None or not spec.origin:
        return None
    library = Path(spec.origin).parent / 'lib' / 'libomp.dylib'
    if not library.is_file():
        return None
    # Retain the handle for the process lifetime and reuse it across backends.
    return ctypes.CDLL(str(library), mode=ctypes.RTLD_GLOBAL)
