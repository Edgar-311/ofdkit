"""Exceptions raised by ofdkit."""


class OFDError(Exception):
    """Base class for all errors raised while reading an OFD file."""


class OFDFormatError(OFDError):
    """The file is not an OFD document, or a required part cannot be read."""


class OFDLimitError(OFDError):
    """The file exceeds a safety limit, such as part size or entry count."""
