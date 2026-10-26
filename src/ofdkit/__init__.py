"""ofdkit: read OFD documents (GB/T 33190) and Chinese e-invoices.

>>> import ofdkit
>>> with ofdkit.open("invoice.ofd") as doc:  # doctest: +SKIP
...     print(doc.text())
...     print(doc.invoice())
"""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _version

from .batch import InvoiceFile, read_invoices
from .document import DocInfo, OFDDocument, Page, TextRun
from .errors import OFDError, OFDFormatError, OFDLimitError
from .invoice import Invoice, LineItem, Party
from .package import Source

try:
    __version__ = _version("ofdkit")
except PackageNotFoundError:  # running from a source checkout that is not installed
    __version__ = "0.0.0+unknown"

__all__ = [
    "DocInfo",
    "Invoice",
    "InvoiceFile",
    "LineItem",
    "OFDDocument",
    "OFDError",
    "OFDFormatError",
    "OFDLimitError",
    "Page",
    "Party",
    "TextRun",
    "__version__",
    "extract_invoice",
    "extract_text",
    "open",
    "read_invoices",
]


def open(source: Source) -> OFDDocument:  # noqa: A001 - mirrors builtins.open on purpose
    """Open an OFD file from a path, bytes, or a binary file object."""
    return OFDDocument(source)


def extract_text(source: Source, page_separator: str = "\n\n") -> str:
    """Return all text of an OFD file in reading order."""
    with OFDDocument(source) as document:
        return document.text(page_separator)


def extract_invoice(source: Source) -> Invoice | None:
    """Return the invoice data of an OFD e-invoice, or None if the file holds none."""
    with OFDDocument(source) as document:
        return document.invoice()
