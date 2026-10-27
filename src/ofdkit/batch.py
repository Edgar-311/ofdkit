"""Many files at once: find OFD files, also inside ZIP archives, and read their invoices.

The tax authority's e-invoice service hands out many invoices as one ZIP archive, so an
archive counts as a folder: each ``.ofd`` file inside it becomes its own result, named
after the archive and its path inside it (``下载.zip/发票1.ofd``).
"""

from __future__ import annotations

import re
import zipfile
import zlib
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from .document import OFDDocument
from .errors import OFDError
from .invoice import Invoice
from .package import MAX_ENTRIES, _entry_name, _normalize

COLUMNS = [
    "file",
    "invoice_number",
    "invoice_code",
    "invoice_type",
    "issue_date",
    "buyer_name",
    "buyer_tax_id",
    "seller_name",
    "seller_tax_id",
    "amount_without_tax",
    "tax_amount",
    "total_amount",
    "items",
    "item_names",
    "warnings",
    "error",
]

NO_INVOICE = "no invoice data"
DUPLICATE = "duplicate invoice number"
BUYER_MISMATCH = "buyer is not"
EMPTY_ARCHIVE = "no .ofd files in this ZIP archive"

#: Largest OFD file, uncompressed, that is read from inside a ZIP archive.
MAX_ARCHIVE_MEMBER_SIZE = 128 * 1024 * 1024


@dataclass
class InvoiceFile:
    """One OFD file read by :func:`read_invoices`."""

    #: The file's path. For a file inside a ZIP archive, the archive's path joined with
    #: the file's path inside it.
    file: str
    #: The invoice, or None when the file could not be read or holds no invoice data.
    invoice: Invoice | None = None
    #: Why there is no invoice.
    error: str | None = None
    #: Another file has the same invoice number (and invoice code, for older invoices).
    duplicate: bool = False
    #: Expected buyer names or tax IDs (see :func:`check_buyer`) this invoice does not match.
    buyer_mismatch: list[str] = field(default_factory=list)


def read_invoices(
    paths: str | Path | Iterable[str | Path], recursive: bool = False, buyer: Sequence[str] = ()
) -> list[InvoiceFile]:
    """Read every OFD file in ``paths``: files, folders and ZIP archives of OFD files.

    Folders are searched for ``.ofd`` files and for ZIP archives that contain some;
    ``recursive`` also searches their subfolders. With ``buyer`` (company names or tax
    IDs), invoices made out to someone else are noted, see :func:`check_buyer`. Raises
    FileNotFoundError if a path does not exist.
    """
    if isinstance(paths, (str, Path)):
        paths = [paths]
    files, missing = find_ofd_files(paths, recursive)
    if missing:
        raise FileNotFoundError(f"{missing[0]} does not exist")
    results = read_invoice_files(files)
    check_buyer(results, buyer)
    return results


def find_ofd_files(paths: Iterable[str | Path], recursive: bool = False) -> tuple[list[Path], list[str]]:
    """Files to read in ``paths``, plus the paths that do not exist.

    Files given directly are always kept. In folders, ``.ofd`` files are kept, and
    ``.zip`` files that contain at least one ``.ofd`` file.
    """
    found: list[Path] = []
    missing: list[str] = []
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            candidates = path.rglob("*") if recursive else path.glob("*")
            for candidate in sorted(candidates):
                if not candidate.is_file():
                    continue
                suffix = candidate.suffix.lower()
                if suffix == ".ofd" or (suffix == ".zip" and _archive_members(candidate)):
                    found.append(candidate)
        elif path.exists():
            found.append(path)
        else:
            missing.append(str(raw))
    return found, missing


def read_invoice_files(files: Sequence[Path], limit: int | None = None) -> list[InvoiceFile]:
    """Read the files found by :func:`find_ofd_files`, expanding ZIP archives.

    With ``limit``, stop after that many OFD files.
    """
    results: list[InvoiceFile] = []
    for path in files:
        remaining = None if limit is None else limit - len(results)
        if remaining is not None and remaining <= 0:
            break
        results.extend(_read_path(Path(path), remaining))
    keys = Counter(key for key in map(_duplicate_key, results) if key)
    for result in results:
        key = _duplicate_key(result)
        result.duplicate = bool(key) and keys[key] > 1
    return results


def invoice_rows(files: Sequence[Path]) -> list[dict[str, Any]]:
    """One row per OFD file, with the columns in :data:`COLUMNS`."""
    return [invoice_row(result) for result in read_invoice_files(files)]


def invoice_row(result: InvoiceFile | Path) -> dict[str, Any]:
    """A result as a flat row with the columns in :data:`COLUMNS`."""
    if not isinstance(result, InvoiceFile):  # a path, as in ofdkit 0.1
        result = _read_one(str(result), result)
    row: dict[str, Any] = dict.fromkeys(COLUMNS, "")
    row["file"] = result.file
    row["error"] = result.error or ""
    invoice = result.invoice
    if invoice is not None:
        warnings = [
            *invoice.warnings,
            *([DUPLICATE] if result.duplicate else []),
            *(f"{BUYER_MISMATCH} {expected}" for expected in result.buyer_mismatch),
        ]
        row.update(
            {
                "invoice_number": invoice.invoice_number or "",
                "invoice_code": invoice.invoice_code or "",
                "invoice_type": invoice.invoice_type or "",
                "issue_date": invoice.issue_date or "",
                "buyer_name": invoice.buyer.name or "",
                "buyer_tax_id": invoice.buyer.tax_id or "",
                "seller_name": invoice.seller.name or "",
                "seller_tax_id": invoice.seller.tax_id or "",
                "amount_without_tax": invoice.amount_without_tax or "",
                "tax_amount": invoice.tax_amount or "",
                "total_amount": invoice.total_amount or "",
                "items": len(invoice.items),
                "item_names": item_names(invoice),
                "warnings": "; ".join(warnings),
            }
        )
    return row


def item_names(invoice: Invoice, limit: int | None = None) -> str:
    """Distinct names of the invoice's line items joined with ；, such as ``*餐饮服务*餐费``.

    With ``limit``, at most that many names are shown, followed by 等 when there are more.
    """
    names = list(dict.fromkeys(item.name for item in invoice.items if item.name))
    if limit is not None and len(names) > limit:
        return "；".join(names[:limit]) + "等"
    return "；".join(names)


_TAX_ID = re.compile(r"(?=.*\d)[0-9A-Z]{15,20}")


def check_buyer(results: Sequence[InvoiceFile], expected: Sequence[str]) -> None:
    """Note the invoices whose buyer is not ``expected`` in :attr:`InvoiceFile.buyer_mismatch`.

    Each expected value is a company name or a tax ID (统一社会信用代码, 15 to 20 letters
    and digits). Names are compared without spaces, case or full-width brackets.
    """
    for result in results:
        if result.invoice is not None:
            result.buyer_mismatch = buyer_mismatch(result.invoice, expected)


def buyer_mismatch(invoice: Invoice, expected: Sequence[str]) -> list[str]:
    """The expected buyer names or tax IDs that ``invoice`` does not match."""
    missed = []
    for value in expected:
        if not value.strip():
            continue
        if _is_tax_id(value):
            matched = _normal_tax_id(invoice.buyer.tax_id or "") == _normal_tax_id(value)
        else:
            matched = _normal_name(invoice.buyer.name or "") == _normal_name(value)
        if not matched:
            missed.append(value.strip())
    return missed


def _is_tax_id(value: str) -> bool:
    return bool(_TAX_ID.fullmatch(_normal_tax_id(value)))


def _normal_tax_id(value: str) -> str:
    return re.sub(r"\s+", "", value).upper()


def _normal_name(value: str) -> str:
    return re.sub(r"\s+", "", value).replace("（", "(").replace("）", ")").casefold()


_TOTALS_WARNING = re.compile(r"amount_without_tax \+ tax_amount != total_amount \((.*) \+ (.*) != (.*)\)")


def problems(result: InvoiceFile) -> list[str]:
    """What is wrong with a result, in Chinese, for people reading a summary."""
    if result.error == NO_INVOICE:
        return ["不是发票（没有发票数据）"]
    if result.error == EMPTY_ARCHIVE:
        return ["压缩包里没有 OFD 文件"]
    if result.error and result.error.startswith("not an OFD file"):
        return [f"读不出来：不是 OFD 文件，或者文件已损坏（{result.error}）"]
    if result.error:
        return [f"读不出来：{result.error}"]
    found = []
    if result.duplicate:
        found.append("发票号码重复")
    invoice = result.invoice
    for expected in result.buyer_mismatch:
        tax_id = _is_tax_id(expected)
        actual = (invoice.buyer.tax_id if tax_id else invoice.buyer.name) if invoice else None
        label = "购买方税号" if tax_id else "购买方"
        found.append(f"{label}不是 {expected}（发票上是 {actual or '空的'}）")
    for warning in invoice.warnings if invoice else []:
        match = _TOTALS_WARNING.fullmatch(warning)
        found.append(f"金额 + 税额 ≠ 价税合计（{match[1]} + {match[2]} ≠ {match[3]}）" if match else warning)
    return found


def summary(results: Sequence[InvoiceFile | dict[str, Any]]) -> dict[str, Any]:
    """Counts and sums over the results (or rows from :func:`invoice_rows`).

    ``total_amount_sum`` adds every invoice; ``total_amount_sum_without_duplicates``
    counts an invoice that appears in several files only once.
    """
    rows = [result if isinstance(result, dict) else invoice_row(result) for result in results]
    invoices = [row for row in rows if not row["error"]]
    seen: set[tuple[str, str]] = set()
    unique: list[dict[str, Any]] = []
    for row in invoices:
        key = (row["invoice_code"], row["invoice_number"])
        if row["invoice_number"] and key in seen:
            continue
        seen.add(key)
        unique.append(row)

    def total(column: str, selected: list[dict[str, Any]]) -> str:
        return str(sum((_decimal(row[column]) for row in selected), Decimal(0)))

    return {
        "files": len(rows),
        "invoices": len(invoices),
        "without_invoice_data": sum(1 for row in rows if row["error"] == NO_INVOICE),
        "errors": sum(1 for row in rows if row["error"] and row["error"] != NO_INVOICE),
        "duplicates": len(invoices) - len(unique),
        "buyer_mismatches": sum(1 for row in invoices if BUYER_MISMATCH in row["warnings"]),
        "amount_without_tax_sum": total("amount_without_tax", invoices),
        "tax_amount_sum": total("tax_amount", invoices),
        "total_amount_sum": total("total_amount", invoices),
        "total_amount_sum_without_duplicates": total("total_amount", unique),
    }


def _read_path(path: Path, limit: int | None = None) -> list[InvoiceFile]:
    if path.suffix.lower() != ".zip":
        return [_read_one(str(path), path)]
    members = _archive_members(path)
    if members is None:  # not a readable archive, or an OFD file named .zip
        return [_read_one(str(path), path)]
    if not members:
        return [InvoiceFile(str(path), error=EMPTY_ARCHIVE)]
    results = []
    try:
        with zipfile.ZipFile(path) as archive:
            for info in members[:limit]:
                label = str(path / _normalize(_entry_name(info)))
                if info.file_size > MAX_ARCHIVE_MEMBER_SIZE:
                    results.append(InvoiceFile(label, error=f"too large to read from the archive ({info.file_size} bytes)"))
                    continue
                try:
                    data = archive.read(info)
                except (zipfile.BadZipFile, zlib.error, RuntimeError, NotImplementedError, EOFError) as exc:
                    # RuntimeError: a password-protected entry.
                    results.append(InvoiceFile(label, error=f"cannot read from the archive: {exc}"))
                    continue
                results.append(_read_one(label, data))
    except (zipfile.BadZipFile, OSError) as exc:
        return [*results, InvoiceFile(str(path), error=f"cannot read the archive: {exc}")]
    return results


def _archive_members(path: Path) -> list[zipfile.ZipInfo] | None:
    """The ``.ofd`` entries of a ZIP archive, or None if ``path`` is no archive of OFD files."""
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
    except (zipfile.BadZipFile, OSError, ValueError, EOFError):
        return None
    if len(infos) > MAX_ENTRIES:
        return None
    names = [(_normalize(_entry_name(info)), info) for info in infos if not info.is_dir()]
    if any(name.casefold() == "ofd.xml" for name, _ in names):  # an OFD file itself
        return None
    return [info for name, info in sorted(names, key=lambda pair: pair[0]) if name.lower().endswith(".ofd")]


def _read_one(label: str, source: Path | bytes) -> InvoiceFile:
    try:
        with OFDDocument(source) as document:
            invoice = document.invoice()
    except (OFDError, OSError) as exc:
        return InvoiceFile(label, error=str(exc))
    if invoice is None:
        return InvoiceFile(label, error=NO_INVOICE)
    return InvoiceFile(label, invoice=invoice)


def _duplicate_key(result: InvoiceFile) -> tuple[str, str] | None:
    """Older invoices are unique only by code and number together; 数电票 have no code."""
    invoice = result.invoice
    if invoice is None or not invoice.invoice_number:
        return None
    return (invoice.invoice_code or "", invoice.invoice_number)


def _decimal(value: str) -> Decimal:
    try:
        return Decimal(value)
    except (InvalidOperation, TypeError):
        return Decimal(0)
