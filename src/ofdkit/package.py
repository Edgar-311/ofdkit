"""The ZIP container of an OFD file: entry lookup, path resolution and safety limits."""

from __future__ import annotations

import io
import os
import posixpath
import xml.etree.ElementTree as ET
import zipfile
import zlib
from typing import BinaryIO, Union

from ._xml import parse_xml
from .errors import OFDFormatError, OFDLimitError

Source = Union[str, "os.PathLike[str]", bytes, bytearray, BinaryIO]

#: Most entries a package may contain.
MAX_ENTRIES = 50_000
#: Largest single part, uncompressed, that ofdkit will read into memory.
MAX_PART_SIZE = 64 * 1024 * 1024

_UTF8_FLAG = 0x800


class Package:
    """Read-only view of the parts inside an OFD file."""

    def __init__(self, source: Source) -> None:
        try:
            if isinstance(source, (bytes, bytearray)):
                self._zip = zipfile.ZipFile(io.BytesIO(bytes(source)))
            else:
                self._zip = zipfile.ZipFile(source)
        except (zipfile.BadZipFile, ValueError, EOFError) as exc:
            raise OFDFormatError(f"not an OFD file (not a ZIP container): {exc}") from exc

        infos = self._zip.infolist()
        if len(infos) > MAX_ENTRIES:
            self.close()
            raise OFDLimitError(f"too many entries in the package ({len(infos)} > {MAX_ENTRIES})")

        self._entries: dict[str, zipfile.ZipInfo] = {}
        for info in infos:
            if info.is_dir():
                continue
            self._entries.setdefault(_normalize(_entry_name(info)), info)
        self._casefolded: dict[str, str] = {}
        for name in self._entries:
            self._casefolded.setdefault(name.casefold(), name)

    @property
    def names(self) -> list[str]:
        """Names of all files in the package."""
        return list(self._entries)

    def find(self, path: str) -> str | None:
        """Return the entry name for ``path``, matching case-insensitively as a fallback."""
        path = _normalize(path)
        if path in self._entries:
            return path
        return self._casefolded.get(path.casefold())

    def resolve(self, base: str | None, location: str | None) -> str | None:
        """Resolve a location written inside ``base`` to an entry name, or None.

        The standard says relative locations are relative to the referencing file and
        absolute ones start at the package root. Producers get this wrong often enough
        that a location is also tried relative to the root, and matched without case.
        """
        location = (location or "").strip().replace("\\", "/")
        if not location:
            return None
        if location.startswith("/"):
            candidates = [location]
        else:
            base_dir = posixpath.dirname(_normalize(base)) if base else ""
            candidates = [posixpath.join(base_dir, location), location]
        for candidate in candidates:
            candidate = posixpath.normpath(_normalize(candidate))
            if candidate == ".." or candidate.startswith("../"):
                continue
            found = self.find(candidate)
            if found is not None:
                return found
        return None

    def read(self, name: str) -> bytes:
        """Read one entry, refusing entries larger than MAX_PART_SIZE."""
        info = self._entries.get(name)
        if info is None:
            raise OFDFormatError(f"missing part: {name}")
        if info.file_size > MAX_PART_SIZE:
            raise OFDLimitError(f"{name} is too large ({info.file_size} bytes)")
        try:
            with self._zip.open(info) as stream:
                data = stream.read(MAX_PART_SIZE + 1)
        except (zipfile.BadZipFile, zlib.error, RuntimeError, NotImplementedError, EOFError, OSError) as exc:
            # RuntimeError: encrypted entry; NotImplementedError: unsupported compression.
            raise OFDFormatError(f"cannot read {name}: {exc}") from exc
        if len(data) > MAX_PART_SIZE:
            raise OFDLimitError(f"{name} is too large when decompressed")
        return data

    def read_xml(self, name: str) -> ET.Element:
        """Read and parse one XML entry."""
        return parse_xml(self.read(name), name)

    def close(self) -> None:
        self._zip.close()

    def __enter__(self) -> Package:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


def _normalize(name: str) -> str:
    name = name.replace("\\", "/")
    while name.startswith(("/", "./")):
        name = name[1:] if name.startswith("/") else name[2:]
    return name


def _entry_name(info: zipfile.ZipInfo) -> str:
    """Decode an entry name the way its producer most likely wrote it.

    Without the UTF-8 flag, zipfile decodes names as CP437, but Chinese tools usually
    stored UTF-8 or GBK bytes there.
    """
    if info.flag_bits & _UTF8_FLAG:
        return info.filename
    try:
        raw = info.filename.encode("cp437")
    except UnicodeEncodeError:
        return info.filename
    if raw.isascii():
        return info.filename
    for encoding in ("utf-8", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return info.filename
