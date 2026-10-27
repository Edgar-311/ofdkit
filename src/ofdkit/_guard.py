"""Keep file access inside one folder, for the MCP server's ``--root`` option.

A path inside the folder can still lead outside it: a symbolic link, a Windows
directory junction, or a folder replaced by a link after it was listed. So every file is
checked by its final, resolved path right before it is opened, and again through the
opened handle; folders that lead outside are not searched at all.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import BinaryIO


class OutsideRootError(PermissionError):
    """A path leads outside the allowed folder."""


class PathGuard:
    """Allows reading files only when their real location is inside ``root``."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(os.path.realpath(Path(root).expanduser()))
        #: Paths that were skipped because they lead outside the folder.
        self.refused: list[str] = []

    def inside(self, path: str | Path) -> bool:
        """True when the real location of ``path`` (all links followed) is inside the folder."""
        real = Path(os.path.realpath(path))
        return real == self.root or self.root in real.parents

    def check(self, path: str | Path) -> Path:
        """The real location of ``path``, or OutsideRootError."""
        real = Path(os.path.realpath(Path(path).expanduser()))
        if not (real == self.root or self.root in real.parents):
            raise OutsideRootError(f"{path} is outside the allowed folder {self.root}")
        return real

    def open(self, path: str | Path) -> BinaryIO:
        """Open a file for reading after checking where it really is.

        The resolved path is opened, not the one given, and the opened handle is compared
        with what the path points at afterwards, so a link swapped in between is caught.
        """
        real = self.check(path)
        stream = open(real, "rb")  # noqa: SIM115 - the caller closes it
        try:
            if not os.path.samestat(os.fstat(stream.fileno()), os.stat(real)) or not self.inside(real):
                raise OutsideRootError(f"{path} changed while it was opened")
        except BaseException:
            stream.close()
            raise
        return stream

    def walk(self, folder: Path, recursive: bool) -> Iterator[Path]:
        """Files in ``folder`` (and its subfolders) whose real location is inside the root.

        Links that lead outside are skipped and noted in :attr:`refused`; folders are
        never entered twice, so link loops end.
        """
        seen: set[str] = set()
        pending = [folder]
        while pending:
            current = pending.pop()
            real = os.path.realpath(current)
            if real in seen:
                continue
            seen.add(real)
            try:
                entries = sorted(current.iterdir())
            except OSError:
                continue
            for entry in entries:
                if not self.inside(entry):
                    self.refused.append(str(entry))
                elif entry.is_dir():
                    if recursive:
                        pending.append(entry)
                elif entry.is_file():
                    yield entry
