"""Reading order: turn positioned text runs into lines of plain text.

The steps, in order:

1. Drop runs drawn twice at the same spot (fake bold).
2. Merge vertical labels: Chinese characters stacked one per line at the same x, as in
   the "购/买/方" labels on e-invoices, become one run at the top character's position.
3. Group runs into lines by baseline and sort each line left to right.
4. Find multi-column regions: consecutive lines whose pieces line up in columns that read
   like prose. Those regions are read column by column; everything else, including
   tables, is read line by line.
5. Join each line's runs with spacing from the gaps between them, and separate
   paragraphs by blank lines.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from typing import Any, Protocol


class _Run(Protocol):
    text: str
    x: float
    y: float
    size: float
    width: float


# Runs whose baselines differ by less than this share of the font size are one line.
_SAME_LINE = 0.5
# A horizontal gap wider than this share of the font size gets a space ...
_WORD_GAP = 0.25
# ... and a gap wider than this one splits a line into separate pieces (columns, cells).
_COLUMN_GAP = 1.5
# A vertical step larger than this many font sizes starts a new paragraph.
_PARAGRAPH_GAP = 2.2
# Smallest size used for tolerances, so tiny or missing font sizes still work.
_MIN_SIZE = 1.0

# Vertical labels: neighbouring characters at most this many font sizes apart ...
_STACK_STEP = 3.0
# ... at the same x within this share of the font size, with 2 to this many characters,
# each with a horizontal gap of more than this share of the font size on both sides.
_STACK_ALIGN = 0.3
_STACK_MAX = 10
_STACK_GAP = 0.5

# Column regions: a piece belongs to a column when it starts within this many font sizes
# of the column's start; a region needs this many lines with two or more pieces, pieces
# of at least this many characters on average, at least this share of each column's
# lines nearly as wide as the column (justified prose; table cells vary), and no
# vertical jump larger than this many font sizes.
_COLUMN_ALIGN = 2.5
_COLUMN_MIN_ROWS = 3
_COLUMN_MIN_CHARS = 6.0
_COLUMN_FULL_LINE = 0.85
_COLUMN_MIN_FULL_SHARE = 0.5
_COLUMN_MAX_STEP = 4.0
# Prose columns are at least this many font sizes wide (about ten Chinese characters).
_COLUMN_MIN_WIDTH = 10.0
# Lines whose type size differs from the columns' by more than this factor are asides.
_COLUMN_SIZE_RATIO = 1.25


def page_text(runs: Sequence[_Run]) -> str:
    """Join runs into text in reading order."""
    runs = _merge_vertical_labels([run for run in _dedupe(runs) if run.text.strip()])
    lines = _group_lines(runs)
    blocks = _blocks(lines)
    return "\n\n".join(text for text in (_render(block) for block in blocks) if text).strip("\n")


def _dedupe(runs: Sequence[_Run]) -> list[_Run]:
    """Drop runs drawn twice at the same spot, a common way to fake bold text."""
    seen: set[tuple[str, int, int]] = set()
    unique = []
    for run in runs:
        key = (run.text, round(run.x * 4), round(run.y * 4))
        if key not in seen:
            seen.add(key)
            unique.append(run)
    return unique


# --------------------------------------------------------------------------- vertical labels


def _is_cjk(char: str) -> bool:
    code = ord(char)
    return (
        0x4E00 <= code <= 0x9FFF
        or 0x3400 <= code <= 0x4DBF
        or 0xF900 <= code <= 0xFAFF
        or 0x20000 <= code <= 0x3134F
    )


def _merge_vertical_labels(runs: list[_Run]) -> list[_Run]:
    """Merge vertical labels.

    A label character is a single Chinese character standing apart from its neighbours on
    the same line. That rules out text drawn one character at a time, whose characters
    touch. A stack counts as a label only if its last character and at least half of all
    its characters have no other text on their line except other label characters: a
    column of one-character table cells (units such as 次, 个) always shares its lines
    with the other cells.
    """
    lines = _group_lines(runs)
    line_of: dict[int, list[_Run]] = {id(run): line for line in lines for run in line}
    singles = sorted((run for line in lines for run in _label_characters(line)), key=lambda r: (r.x, r.y))
    single_ids = {id(run) for run in singles}

    def alone(run: _Run) -> bool:
        return all(id(other) in single_ids for other in line_of[id(run)] if other is not run)

    used: set[int] = set()
    merged: dict[int, _Run] = {}
    for start in singles:
        if id(start) in used:
            continue
        chain = [start]
        while len(chain) < _STACK_MAX + 1:
            last = chain[-1]
            size = max(last.size, _MIN_SIZE)
            nearest = None
            for candidate in singles:
                if id(candidate) in used or candidate is last or candidate in chain:
                    continue
                step = candidate.y - last.y
                if (
                    0 < step <= _STACK_STEP * size
                    and abs(candidate.x - last.x) <= _STACK_ALIGN * size
                    and abs(candidate.size - last.size) <= 0.1 * size
                    and (nearest is None or step < nearest.y - last.y)
                ):
                    nearest = candidate
            if nearest is None:
                break
            chain.append(nearest)
        # A label's first character may share a line with the first row of content, but it
        # does not end on a character that shares its line: that is usually the next thing
        # below, such as a table header (密码区 above 单价).
        while chain and not alone(chain[-1]):
            chain.pop()
        if 2 <= len(chain) <= _STACK_MAX and 2 * sum(alone(run) for run in chain) >= len(chain):
            used.update(id(run) for run in chain)
            text = "".join(run.text.strip() for run in chain)
            merged[id(start)] = _replace(start, text=text, width=max(start.size, _MIN_SIZE))
    if not merged:
        return runs
    return [merged.get(id(run), run) for run in runs if id(run) not in used or id(run) in merged]


def _label_characters(line: list[_Run]) -> list[_Run]:
    """Single Chinese characters on a line (sorted by x) with a clear gap on both sides."""
    found = []
    for index, run in enumerate(line):
        text = run.text.strip()
        if len(text) != 1 or not _is_cjk(text):
            continue
        gap = _STACK_GAP * max(run.size, _MIN_SIZE)
        if index > 0 and run.x - (line[index - 1].x + line[index - 1].width) <= gap:
            continue
        if index + 1 < len(line) and line[index + 1].x - (run.x + run.width) <= gap:
            continue
        found.append(run)
    return found


def _replace(run: _Run, **changes: Any) -> _Run:
    if dataclasses.is_dataclass(run) and not isinstance(run, type):
        return dataclasses.replace(run, **changes)
    copy = type("Run", (), {})()
    for name in ("text", "x", "y", "size", "width"):
        setattr(copy, name, changes.get(name, getattr(run, name)))
    return copy  # type: ignore[return-value]


# --------------------------------------------------------------------------- lines and blocks


def _group_lines(runs: list[_Run]) -> list[list[_Run]]:
    lines: list[list[_Run]] = []
    for run in sorted(runs, key=lambda r: (r.y, r.x)):
        if lines:
            line = lines[-1]
            anchor = line[0]
            tolerance = _SAME_LINE * max(min(run.size, anchor.size), _MIN_SIZE)
            if abs(run.y - anchor.y) <= tolerance:
                line.append(run)
                continue
        lines.append([run])
    for line in lines:
        line.sort(key=lambda r: r.x)
    return lines


def _pieces(line: list[_Run]) -> list[list[_Run]]:
    """Split a line where the gap between runs is wide enough to separate columns or cells."""
    pieces = [[line[0]]]
    for previous, run in zip(line, line[1:]):
        size = max(min(previous.size, run.size), _MIN_SIZE)
        if run.x - (previous.x + previous.width) > _COLUMN_GAP * size:
            pieces.append([run])
        else:
            pieces[-1].append(run)
    return pieces


def _blocks(lines: list[list[_Run]]) -> list[list[list[_Run]]]:
    """Lines grouped into blocks read one after another; a column region gives one block per column."""
    blocks: list[list[list[_Run]]] = []
    current: list[list[_Run]] = []
    pieces = [_pieces(line) for line in lines]
    index = 0
    while index < len(lines):
        region = _column_region(pieces, index) if len(pieces[index]) >= 2 else None
        if region is None:
            current.append(lines[index])
            index += 1
            continue
        end, columns, asides = region
        if current:
            blocks.append(current)
            current = []
        blocks.extend(column for column in columns if column)
        if asides:
            blocks.append(asides)
        index = end
    if current:
        blocks.append(current)
    return blocks


def _column_region(
    pieces: list[list[list[_Run]]], first: int
) -> tuple[int, list[list[list[_Run]]], list[list[_Run]]] | None:
    """Columns starting at line ``first``, or None.

    Returns the index after the region, the lines of each column, and asides: pieces in a
    clearly different type size inside the region, such as photo captions, which are kept
    out of the columns and read after them.
    """
    starts = [piece[0].x for piece in pieces[first]]
    size = max(min(run.size for piece in pieces[first] for run in piece), _MIN_SIZE)
    columns: list[list[list[_Run]]] = [[] for _ in starts]
    asides: list[list[_Run]] = []
    multi_rows = 0
    previous_y = pieces[first][0][0].y
    index = first
    while index < len(pieces):
        row = pieces[index]
        if row[0][0].y - previous_y > _COLUMN_MAX_STEP * size:
            break
        body = [piece for piece in row if _same_size(piece, size)]
        others = [piece for piece in row if not _same_size(piece, size)]
        if not body:
            asides.extend(others)
            index += 1
            continue
        placed = _place(body, starts, size)
        if placed is None:
            break
        asides.extend(others)
        row = body
        for column, piece in placed:
            columns[column].append(piece)
        multi_rows += len(row) >= 2
        previous_y = row[0][0].y
        index += 1

    if multi_rows < _COLUMN_MIN_ROWS:
        return None
    for column in columns:
        if not column:
            return None
        chars = sum(len("".join(run.text for run in piece).replace(" ", "")) for piece in column) / len(column)
        if chars < _COLUMN_MIN_CHARS:
            return None
        # Justified prose fills its column's width on most lines. Measure against the column
        # itself, since pictures or white space may lie between columns.
        span = max(max(_right(piece) for piece in column) - min(piece[0].x for piece in column), size)
        if span < _COLUMN_MIN_WIDTH * size:
            return None
        full = sum(_right(piece) - piece[0].x >= _COLUMN_FULL_LINE * span for piece in column)
        if full < _COLUMN_MIN_FULL_SHARE * len(column):
            return None
    return index, columns, asides


def _same_size(piece: list[_Run], size: float) -> bool:
    piece_size = max(min(run.size for run in piece), _MIN_SIZE)
    return 1 / _COLUMN_SIZE_RATIO <= piece_size / size <= _COLUMN_SIZE_RATIO


def _place(row: list[list[_Run]], starts: list[float], size: float) -> list[tuple[int, list[_Run]]] | None:
    """Assign each piece of a line to a column, or None if the line does not fit the columns."""
    tolerance = _COLUMN_ALIGN * size
    placed: list[tuple[int, list[_Run]]] = []
    taken: set[int] = set()
    for piece in row:
        x = piece[0].x
        column = None
        for number, start in enumerate(starts):
            following = starts[number + 1] if number + 1 < len(starts) else None
            if x >= start - tolerance and (following is None or x < following - tolerance):
                column = number
                break
        if column is None or column in taken:
            return None
        following = starts[column + 1] if column + 1 < len(starts) else None
        if following is not None and _right(piece) > following - 0.5 * size:
            return None  # the piece reaches into the next column, like a heading across both
        taken.add(column)
        placed.append((column, piece))
    return placed


def _right(piece: list[_Run]) -> float:
    return max(run.x + run.width for run in piece)


# --------------------------------------------------------------------------- rendering


def _render(lines: list[list[_Run]]) -> str:
    out: list[str] = []
    previous_y: float | None = None
    previous_size = _MIN_SIZE
    for line in lines:
        size = max(min(run.size for run in line), _MIN_SIZE)
        y = line[0].y
        if previous_y is not None and y - previous_y > _PARAGRAPH_GAP * max(size, previous_size):
            out.append("")
        out.append(_join_line(line))
        previous_y, previous_size = y, size
    return "\n".join(out).strip("\n")


def _join_line(line: list[_Run]) -> str:
    parts = [line[0].text]
    for previous, run in zip(line, line[1:]):
        size = max(min(previous.size, run.size), _MIN_SIZE)
        gap = run.x - (previous.x + previous.width)
        if gap > _COLUMN_GAP * size:
            parts.append("   ")
        elif gap > _WORD_GAP * size:
            parts.append(" ")
        parts.append(run.text)
    # Leading spaces are layout, not content, and would start a code block in Markdown.
    return "".join(parts).strip()
