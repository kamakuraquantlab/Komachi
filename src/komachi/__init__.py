"""Komachi: the Kamakura Quant Lab command line client."""

from importlib.metadata import PackageNotFoundError, version

from .settings import data_root

try:
    __version__ = version("kamakuraquantlab-komachi")
except PackageNotFoundError:        # a source tree that was never installed
    __version__ = "0.0.0+source"

__all__ = ["data_root", "__version__"]
