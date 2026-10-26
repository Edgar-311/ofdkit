"""MarkItDown plugin: convert OFD files to Markdown with ``markitdown --use-plugins``.

Install with ``pip install "ofdkit[markitdown]"``. MarkItDown finds the plugin through the
``markitdown.plugin`` entry point declared in ofdkit's package metadata.
"""

from __future__ import annotations

import zipfile
from typing import Any, BinaryIO

from markitdown import DocumentConverter, DocumentConverterResult, StreamInfo

from .document import OFDDocument
from .markdown import document_markdown

__plugin_interface_version__ = 1

ACCEPTED_EXTENSIONS = (".ofd",)
ACCEPTED_MIME_TYPES = ("application/ofd", "application/x-ofd")


class OfdConverter(DocumentConverter):
    """Converts OFD documents (GB/T 33190) to Markdown."""

    def accepts(self, file_stream: BinaryIO, stream_info: StreamInfo, **kwargs: Any) -> bool:
        if (stream_info.extension or "").lower() in ACCEPTED_EXTENSIONS:
            return True
        if (stream_info.mimetype or "").lower().split(";")[0].strip() in ACCEPTED_MIME_TYPES:
            return True
        return _looks_like_ofd(file_stream)

    def convert(self, file_stream: BinaryIO, stream_info: StreamInfo, **kwargs: Any) -> DocumentConverterResult:
        with OFDDocument(file_stream.read()) as document:
            return DocumentConverterResult(markdown=document_markdown(document), title=document.info.title)


def register_converters(markitdown: Any, **kwargs: Any) -> None:
    """Called by MarkItDown when plugins are enabled."""
    markitdown.register_converter(OfdConverter())


def _looks_like_ofd(file_stream: BinaryIO) -> bool:
    """A ZIP file whose root holds OFD.xml. The stream position is restored."""
    position = file_stream.tell()
    try:
        if file_stream.read(4) != b"PK\x03\x04":
            return False
        file_stream.seek(position)
        with zipfile.ZipFile(file_stream) as archive:
            return any(name.lstrip("/").lower() == "ofd.xml" for name in archive.namelist())
    except (zipfile.BadZipFile, OSError, ValueError, EOFError):
        return False
    finally:
        file_stream.seek(position)
