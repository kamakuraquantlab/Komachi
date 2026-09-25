"""Komachi: the Kamakura Quant Lab command line client."""

from importlib.metadata import PackageNotFoundError, version

from . import bronze
from .settings import data_root

try:
    __version__ = version("kamakuraquantlab-komachi")
except PackageNotFoundError:        # a source tree that was never installed
    __version__ = "0.0.0+source"

# `bronze` is the library face of what Komachi owns: it writes that layer, so
# it answers what is in it. Hase and anything else in the ecosystem read it
# from here rather than globbing the tree themselves.
__all__ = ["bronze", "data_root", "__version__"]
