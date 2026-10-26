"""MCP server: lets AI tools (Claude, Codex, Cursor and others) read OFD files.

Run it with ``ofdkit mcp`` after ``pip install "ofdkit[mcp]"``, or without installing
anything: ``uvx --from "ofdkit[mcp]" ofdkit mcp``. Every tool only reads files.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from . import __version__
from .batch import find_ofd_files, invoice_rows, summary
from .cli import file_info
from .document import OFDDocument
from .errors import OFDError
from .markdown import document_markdown

#: Most files list_ofd_invoices reads in one call.
MAX_BATCH_FILES = 500

INSTRUCTIONS = """\
Reads OFD files (GB/T 33190), the Chinese fixed-layout format used for e-invoices
(电子发票, 数电票) and official documents. Pass absolute file paths.
Use read_ofd_invoice for invoice fields, read_ofd_text for any document's text, and
list_ofd_invoices to summarise a folder of invoices. Values are what the file
contains; they are not checked against the tax authority."""

_READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)


def create_server(root: str | Path | None = None) -> MCPServer:
    """Build the server. With ``root`` set, only files inside that folder can be read."""
    allowed = Path(root).expanduser().resolve() if root else None
    server = MCPServer(name="ofdkit", version=__version__, instructions=INSTRUCTIONS)

    def check(path: str) -> Path:
        resolved = Path(path).expanduser().resolve()
        if allowed is not None and not resolved.is_relative_to(allowed):
            raise ToolError(f"{path} is outside the allowed folder {allowed}")
        if not resolved.exists():
            raise ToolError(f"{path} does not exist")
        return resolved

    def open_document(path: str) -> OFDDocument:
        try:
            return OFDDocument(check(path))
        except OFDError as exc:
            raise ToolError(f"cannot read {path}: {exc}") from exc

    @server.tool(title="Read OFD text", annotations=_READ_ONLY)
    def read_ofd_text(path: str, markdown: bool = False, first_page: int = 1, last_page: int | None = None) -> str:
        """Extract the text of an OFD file in reading order.

        Args:
            path: Absolute path to the .ofd file.
            markdown: Return Markdown; e-invoices then start with a table of their fields.
            first_page: First page to include, counting from 1.
            last_page: Last page to include; all remaining pages if omitted.
        """
        with open_document(path) as document:
            if markdown and first_page == 1 and last_page is None:
                return document_markdown(document)
            pages = document.pages[max(first_page, 1) - 1 : last_page]
            if not pages:
                raise ToolError(f"no pages in range {first_page}-{last_page}; the file has {len(document.pages)} pages")
            texts = []
            for page in pages:
                try:
                    text = page.text()
                except OFDError as exc:
                    text = f"[page {page.index + 1} could not be read: {exc}]"
                texts.append(f"## 第 {page.index + 1} 页\n\n{text}" if markdown else text)
            return "\n\n".join(texts)

    @server.tool(title="Read OFD invoice", annotations=_READ_ONLY)
    def read_ofd_invoice(path: str) -> dict[str, Any]:
        """Read the fields of a Chinese e-invoice (数电票 or 增值税电子发票) in OFD format.

        Returns invoice number and code, the invoice type as printed (such as
        电子发票（增值税专用发票）; 专用发票 can be used for VAT deduction, 普通发票 cannot),
        issue date (YYYY-MM-DD), buyer and seller, amounts as decimal strings, line items,
        and warnings such as totals that do not add up.

        Args:
            path: Absolute path to the .ofd file.
        """
        with open_document(path) as document:
            invoice = document.invoice()
        if invoice is None:
            raise ToolError(f"no invoice data in {path}; use read_ofd_text to read its text")
        return invoice.to_dict()

    @server.tool(title="OFD file info", annotations=_READ_ONLY)
    def ofd_info(path: str) -> dict[str, Any]:
        """Pages (with sizes in millimetres), metadata, and whether an OFD file is an invoice.

        Args:
            path: Absolute path to the .ofd file.
        """
        with open_document(path) as document:
            return file_info(document, path)

    @server.tool(title="List OFD invoices in a folder", annotations=_READ_ONLY)
    def list_ofd_invoices(folder: str, recursive: bool = False) -> dict[str, Any]:
        """Summarise every invoice in a folder of .ofd files.

        Returns one row per file (number, date, buyer, seller, amounts, or the reason it
        could not be read), duplicate invoice numbers flagged, and totals.

        Args:
            folder: Absolute path to a folder.
            recursive: Also look in subfolders.
        """
        directory = check(folder)
        if not directory.is_dir():
            raise ToolError(f"{folder} is not a folder")
        files, _ = find_ofd_files([directory], recursive)
        truncated = len(files) > MAX_BATCH_FILES
        rows = invoice_rows(files[:MAX_BATCH_FILES])
        return {"summary": summary(rows), "truncated": truncated, "rows": rows}

    return server
