"""ofdkit: read OFD documents (GB/T 33190) and Chinese e-invoices."""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _version

try:
    __version__ = _version("ofdkit")
except PackageNotFoundError:  # running from a source checkout that is not installed
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
