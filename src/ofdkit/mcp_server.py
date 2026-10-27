"""MCP server: lets AI tools (Claude, Codex, Cursor and others) read OFD files.

Run it with ``ofdkit mcp`` after ``pip install "ofdkit[mcp]"``, or without installing
anything: ``uvx --from "ofdkit[mcp]" ofdkit mcp``. Every tool only reads files.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from . import __version__
from ._guard import OutsideRootError, PathGuard
from .batch import check_buyer, find_ofd_files, invoice_row, read_invoice_files, summary
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
    """Build the server. With ``root`` set, only files inside that folder can be read.

    The check uses each file's real location with every link followed (symbolic links,
    Windows directory junctions), right before the file is opened, for single files as
    well as for every file a folder listing reads.
    """
    server = MCPServer(name="ofdkit", version=__version__, instructions=INSTRUCTIONS)

    def new_guard() -> PathGuard | None:
        return PathGuard(root) if root else None

    def check(path: str, guard: PathGuard | None) -> Path:
        try:
            resolved = guard.check(path) if guard is not None else Path(path).expanduser().resolve()
        except OutsideRootError as exc:
            raise ToolError(str(exc)) from exc
        if not resolved.exists():
            raise ToolError(f"{path} does not exist")
        return resolved

    @contextmanager
    def open_document(path: str) -> Iterator[OFDDocument]:
        guard = new_guard()
        resolved = check(path, guard)
        try:
            stream = guard.open(resolved) if guard is not None else open(resolved, "rb")  # noqa: SIM115
        except OutsideRootError as exc:
            raise ToolError(str(exc)) from exc
        except OSError as exc:
            raise ToolError(f"cannot read {path}: {exc}") from exc
        with stream:
            try:
                document = OFDDocument(stream)
            except OFDError as exc:
                raise ToolError(f"cannot read {path}: {exc}") from exc
            with document:
                yield document

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
        电子发票（增值税专用发票）), issue date (YYYY-MM-DD), buyer and seller, amounts as
        decimal strings, line items, and warnings such as totals that do not add up.

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
    def list_ofd_invoices(folder: str, recursive: bool = False, buyer: list[str] | None = None) -> dict[str, Any]:
        """Summarise every invoice in a folder of .ofd files, including ZIP archives of them.

        Returns one row per file (number, date, buyer, seller, amounts, item names, or the
        reason it could not be read), duplicate invoices flagged, and totals with and
        without duplicates.

        Args:
            folder: Absolute path to a folder.
            recursive: Also look in subfolders.
            buyer: The company the invoices should be made out to (发票抬头): its name, its
                tax ID, or both. Invoices for another buyer get a "buyer is not" warning
                and are counted in summary.buyer_mismatches.
        """
        guard = new_guard()
        directory = check(folder, guard)
        if not directory.is_dir():
            raise ToolError(f"{folder} is not a folder")
        files, _ = find_ofd_files([directory], recursive, guard=guard)
        results = read_invoice_files(files, limit=MAX_BATCH_FILES + 1, guard=guard)
        truncated = len(results) > MAX_BATCH_FILES
        results = results[:MAX_BATCH_FILES]
        check_buyer(results, buyer or [])
        listing = {"summary": summary(results), "truncated": truncated, "rows": [invoice_row(r) for r in results]}
        if guard is not None:
            # Links that lead outside the allowed folder: counted, never read.
            listing["skipped_outside_root"] = len(guard.refused)
        return listing

    return server
