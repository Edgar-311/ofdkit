"""Many files at once: find OFD files and summarise their invoices as rows."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from .document import OFDDocument
from .errors import OFDError
from .invoice import Invoice

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
    "warnings",
    "error",
]

NO_INVOICE = "no invoice data"


def find_ofd_files(paths: Iterable[str | Path], recursive: bool = False) -> tuple[list[Path], list[str]]:
    """OFD files in ``paths`` (files are kept, folders are searched), plus paths that do not exist."""
    found: list[Path] = []
    missing: list[str] = []
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            candidates = path.rglob("*") if recursive else path.glob("*")
            found.extend(sorted(p for p in candidates if p.is_file() and p.suffix.lower() == ".ofd"))
        elif path.exists():
            found.append(path)
        else:
            missing.append(str(raw))
    return found, missing


def invoice_rows(files: Sequence[Path]) -> list[dict[str, Any]]:
    """One row per file, with duplicate invoice numbers flagged in ``warnings``."""
    rows = [invoice_row(path) for path in files]
    numbers = Counter(row["invoice_number"] for row in rows if row["invoice_number"])
    for row in rows:
        if numbers.get(row["invoice_number"], 0) > 1:
            row["warnings"] = "; ".join(filter(None, [row["warnings"], "duplicate invoice number"]))
    return rows


def invoice_row(path: Path) -> dict[str, Any]:
    row: dict[str, Any] = dict.fromkeys(COLUMNS, "")
    row["file"] = str(path)
    try:
        with OFDDocument(path) as document:
            invoice = document.invoice()
    except (OFDError, OSError) as exc:
        row["error"] = str(exc)
        return row
    if invoice is None:
        row["error"] = NO_INVOICE
        return row
    row.update(_invoice_columns(invoice))
    return row


def summary(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Counts and the sum of ``total_amount`` over rows that are invoices."""
    invoices = [row for row in rows if not row["error"]]
    total = sum((_decimal(row["total_amount"]) for row in invoices), Decimal(0))
    return {
        "files": len(rows),
        "invoices": len(invoices),
        "without_invoice_data": sum(1 for row in rows if row["error"] == NO_INVOICE),
        "errors": sum(1 for row in rows if row["error"] and row["error"] != NO_INVOICE),
        "total_amount_sum": str(total),
    }


def _invoice_columns(invoice: Invoice) -> dict[str, Any]:
    return {
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
        "warnings": "; ".join(invoice.warnings),
    }


def _decimal(value: str) -> Decimal:
    try:
        return Decimal(value)
    except (InvalidOperation, TypeError):
        return Decimal(0)
