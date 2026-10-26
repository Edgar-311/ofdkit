"""Reading order: turn positioned text runs into lines of plain text."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol


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
# ... and a gap wider than this one marks separate columns.
_COLUMN_GAP = 1.5
# A vertical step larger than this many font sizes starts a new paragraph.
_PARAGRAPH_GAP = 2.2
# Smallest size used for tolerances, so tiny or missing font sizes still work.
_MIN_SIZE = 1.0


def page_text(runs: Sequence[_Run]) -> str:
    """Join runs into text, top to bottom and left to right."""
    lines = _group_lines([run for run in _dedupe(runs) if run.text.strip()])
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
