"""Rename invoice files after what they contain, such as ``2026-01-02_测试单位乙_106.00_00000001.ofd``.

Invoices arrive with names like ``dzfp_24312000000123456789_某某公司_20260102.ofd``, or
worse. :func:`plan` works out new names from a pattern without touching anything;
:func:`apply` renames, never over an existing file, and writes a log that
:func:`undo` can use to restore the old names. Files with the same name and another
extension (the PDF and XML copies of the same invoice) are renamed along with the OFD.
"""

from __future__ import annotations

import csv
import datetime as dt
import os
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from .batch import _duplicate_key, _read_one, find_ofd_files, item_names, problems
from .invoice import Invoice

DEFAULT_PATTERN = "{开票日期}_{销售方}_{价税合计}_{发票号码}"

#: Extensions of copies of the same invoice that are renamed together with the OFD file.
COMPANION_SUFFIXES = (".pdf", ".xml", ".png", ".jpg", ".jpeg")

#: Longest new name, in characters, without the extension.
MAX_NAME_LENGTH = 120

_FIELD_GETTERS: dict[str, Callable[[Invoice, Path], str | None]] = {
    "开票日期": lambda i, p: i.issue_date,
    "发票号码": lambda i, p: i.invoice_number,
    "发票代码": lambda i, p: i.invoice_code,
    "发票种类": lambda i, p: i.invoice_type,
    "销售方": lambda i, p: i.seller.name,
    "销售方税号": lambda i, p: i.seller.tax_id,
    "购买方": lambda i, p: i.buyer.name,
    "购买方税号": lambda i, p: i.buyer.tax_id,
    "金额": lambda i, p: i.amount_without_tax,
    "税额": lambda i, p: i.tax_amount,
    "价税合计": lambda i, p: i.total_amount,
    "商品": lambda i, p: item_names(i, limit=1),
    "原文件名": lambda i, p: p.stem,
}
#: English names for the fields, for people who prefer typing them.
_ALIASES = {
    "date": "开票日期",
    "number": "发票号码",
    "code": "发票代码",
    "type": "发票种类",
    "seller": "销售方",
    "seller_tax_id": "销售方税号",
    "buyer": "购买方",
    "buyer_tax_id": "购买方税号",
    "amount": "金额",
    "tax": "税额",
    "total": "价税合计",
    "item": "商品",
    "name": "原文件名",
}
FIELDS = tuple(_FIELD_GETTERS)

_PLACEHOLDER = re.compile(r"\{([^{}]*)\}")
_NOT_IN_NAMES = re.compile(r'[\\/:*?"<>|\x00-\x1f\x7f]')  # not allowed in Windows file names
_RESERVED = re.compile(r"(?i)(con|prn|aux|nul|com\d|lpt\d)(\..*)?")  # reserved names on Windows


@dataclass
class Rename:
    """What happens to one OFD file."""

    source: Path
    #: The new path, or None when the file keeps its name.
    target: Path | None = None
    #: Why the file keeps its name, in Chinese.
    skipped: str | None = None
    #: Other copies of the same invoice, renamed with it: (old path, new path).
    companions: list[tuple[Path, Path]] = field(default_factory=list)
    #: Another file holds the same invoice.
    duplicate: bool = False


@dataclass
class Outcome:
    """What :func:`apply` or :func:`undo` did."""

    #: Renames that were done: (old path, new path).
    done: list[tuple[Path, Path]] = field(default_factory=list)
    #: Renames that failed: (old path, new path, reason in Chinese).
    failed: list[tuple[Path, Path, str]] = field(default_factory=list)
    #: The log that :func:`undo` reads, if one was written.
    log: Path | None = None


def check_pattern(pattern: str) -> None:
    """Raise ValueError naming the problem if ``pattern`` cannot be used."""
    names = _PLACEHOLDER.findall(pattern)
    if not names:
        raise ValueError(f"命名格式里没有任何字段，例如 {DEFAULT_PATTERN}")
    unknown = [name for name in names if _field(name) is None]
    if unknown:
        raise ValueError(f"不认识的字段：{'、'.join(unknown)}。可以用的字段：{'、'.join(FIELDS)}")
    if _NOT_IN_NAMES.search(_PLACEHOLDER.sub("", pattern)):
        raise ValueError('命名格式里不能有这些字符：\\ / : * ? " < > |')


def new_name(invoice: Invoice, source: Path, pattern: str = DEFAULT_PATTERN) -> str:
    """The new name for ``source``, without its extension. Empty if every field is empty."""
    check_pattern(pattern)

    def value(match: re.Match[str]) -> str:
        getter = _FIELD_GETTERS[_field(match[1]) or ""]
        return _clean(getter(invoice, source) or "")

    name = _PLACEHOLDER.sub(value, pattern)
    for separator in "_- ":  # fields that were empty leave doubled separators
        name = re.sub(f"{re.escape(separator)}{{2,}}", separator, name)
    name = name.strip("_- .")[:MAX_NAME_LENGTH].rstrip("_- .")
    if _RESERVED.fullmatch(name):
        name = "_" + name
    return name


def plan(
    paths: Iterable[str | Path],
    pattern: str = DEFAULT_PATTERN,
    recursive: bool = False,
    companions: bool = True,
) -> list[Rename]:
    """Work out new names for the OFD invoices in ``paths``; nothing is renamed.

    Raises FileNotFoundError if a path does not exist and ValueError for a bad pattern.
    """
    check_pattern(pattern)
    files, missing = find_ofd_files(paths, recursive)
    if missing:
        raise FileNotFoundError(f"{missing[0]} does not exist")

    renames: list[Rename] = []
    taken: dict[Path, set[str]] = {}  # per folder: names in use, case-folded
    keys: dict[tuple[str, str], int] = {}
    for source in files:
        rename = Rename(source)
        renames.append(rename)
        if source.suffix.lower() != ".ofd":
            rename.skipped = "压缩包里的文件不能改名" if source.suffix.lower() == ".zip" else "不是 .ofd 文件"
            continue
        result = _read_one(str(source), source)
        if result.invoice is None:
            rename.skipped = problems(result)[0]
            continue
        key = _duplicate_key(result)
        if key:
            keys[key] = keys.get(key, 0) + 1
            rename.duplicate = keys[key] > 1

        stem = new_name(result.invoice, source, pattern)
        if not stem:
            rename.skipped = "发票上没有命名需要的内容"
            continue
        folder = source.parent
        if folder not in taken:
            taken[folder] = {entry.name.casefold() for entry in _entries(folder)}
        copies = _companions(source) if companions else []
        suffixes = [source.suffix, *(copy.suffix for copy in copies)]
        own = {path.name.casefold() for path in [source, *copies]}  # names this file may keep
        stem = _free_stem(stem, suffixes, taken[folder] - own)
        if stem.casefold() == source.stem.casefold():  # also true for a name that got " (2)" last time
            rename.skipped = "已经是这个名字"
            continue
        rename.target = source.with_name(stem + source.suffix)
        rename.companions = [(copy, copy.with_name(stem + copy.suffix)) for copy in copies]
        for suffix in suffixes:
            taken[folder].add((stem + suffix).casefold())
    return renames


def apply(renames: Sequence[Rename], log_folder: str | Path | None = None) -> Outcome:
    """Rename the files in ``renames``, never over an existing file.

    The log of what was renamed is written to ``log_folder`` (by default the folder of
    the first renamed file) as ``改名记录_<date>_<time>.csv``, for :func:`undo`.
    """
    outcome = Outcome()
    for rename in renames:
        if rename.target is None:
            continue
        for old, new in [(rename.source, rename.target), *rename.companions]:
            _move(old, new, outcome)
            if outcome.failed and outcome.failed[-1][0] == rename.source:
                break  # the OFD file kept its name, so its copies keep theirs too
    if outcome.done:
        folder = Path(log_folder) if log_folder is not None else outcome.done[0][1].parent
        stamp = dt.datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")  # local time, as people read it
        outcome.log = _unused(folder / f"改名记录_{stamp}.csv")
        with open(outcome.log, "w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.writer(stream)
            writer.writerow(["原来的文件", "新的文件"])
            writer.writerows((str(old.resolve()), str(new.resolve())) for old, new in outcome.done)
    return outcome


def undo(log: str | Path) -> Outcome:
    """Give the files listed in a log written by :func:`apply` their old names back."""
    with open(log, newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.reader(stream))
    if not rows or rows[0] != ["原来的文件", "新的文件"]:
        raise ValueError(f"{log} 不是 ofdkit 写的改名记录")
    outcome = Outcome()
    for row in reversed(rows[1:]):
        if len(row) == 2:
            _move(Path(row[1]), Path(row[0]), outcome)
    return outcome


def _move(old: Path, new: Path, outcome: Outcome) -> None:
    if not old.exists():
        outcome.failed.append((old, new, "文件不见了"))
        return
    if new.exists() and not _same_file(old, new):
        outcome.failed.append((old, new, "新名字已经有文件在用"))
        return
    try:
        os.rename(old, new)
    except OSError as exc:
        reason = "文件可能正在被别的软件打开" if isinstance(exc, PermissionError) else str(exc)
        outcome.failed.append((old, new, reason))
        return
    outcome.done.append((old, new))


def _same_file(a: Path, b: Path) -> bool:
    """True when ``b`` is ``a`` under a name that differs only in case."""
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def _field(name: str) -> str | None:
    name = name.strip()
    if name in _FIELD_GETTERS:
        return name
    return _ALIASES.get(name.lower())


def _clean(value: str) -> str:
    value = re.sub(r"^\*([^*]+)\*", r"\1-", value.strip())  # *餐饮服务*餐费 -> 餐饮服务-餐费
    return " ".join(_NOT_IN_NAMES.sub("", value).split())


def _entries(folder: Path) -> list[Path]:
    try:
        return list(folder.iterdir())
    except OSError:
        return []


def _companions(source: Path) -> list[Path]:
    stem = source.stem.casefold()
    return sorted(
        entry
        for entry in _entries(source.parent)
        if entry != source
        and entry.is_file()
        and entry.stem.casefold() == stem
        and entry.suffix.lower() in COMPANION_SUFFIXES
    )


def _free_stem(stem: str, suffixes: list[str], taken: set[str]) -> str:
    candidate, number = stem, 1
    while any((candidate + suffix).casefold() in taken for suffix in suffixes):
        number += 1
        candidate = f"{stem} ({number})"
    return candidate


def _unused(path: Path) -> Path:
    candidate, number = path, 1
    while candidate.exists():
        number += 1
        candidate = path.with_name(f"{path.stem} ({number}){path.suffix}")
    return candidate
