"""Describe an OFD file's structure with every piece of content masked.

The output is meant for bug reports: it shows the package entries, how each XML part is
encoded and nested, and every number that places things on the page, so a maintainer can
rebuild the same structure in a synthetic test file. Text is masked character by
character (Chinese characters become 字, digits 0, letters x or X), so invoice numbers,
names, tax IDs and amounts are not revealed. Images, fonts and other binary parts are
listed by size only.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
import zipfile
from typing import Any

from . import __version__
from ._xml import declared_encoding, local_name, parse_xml_reporting
from .errors import OFDError, OFDFormatError
from .package import Package, Source, _entry_name

#: Most XML elements included across the whole description; the rest are counted.
MAX_ELEMENTS = 20_000

# Element text kept as is when it looks like a location, a number list or an ID: the
# structure needs these, and they carry no personal data.
_STRUCTURAL_TEXT = {
    "DocRoot", "FileLoc", "PublicRes", "DocumentRes", "PageRes", "CustomTags", "Annotations",
    "Attachments", "Extensions", "Signatures", "Outlines", "Bookmarks", "MaxUnitID",
    "PhysicalBox", "ApplicationBox", "ContentBox", "BleedBox", "ObjectRef", "AbbreviatedData",
    "Version", "DocType", "MediaFile", "FontFile", "SignedValue", "SignedInfo",
}
_SAFE_TEXT = re.compile(r"^[A-Za-z0-9_./\\:\- ]*$")
_SAFE_ATTRIBUTE = re.compile(r"^[A-Za-z0-9_./\\:\-+ ,#%()]*$")
# Attributes whose values are names or free text, masked even when they look harmless.
_TEXT_ATTRIBUTES = {"Name", "Title", "FileName", "Creator", "Author", "Subject", "Value"}
# Font names help with font problems and are never personal data: kept as they are.
_KEEP_ATTRIBUTES = {"FontName", "FamilyName"}
_MAX_TEXT = 200


def describe(source: Source) -> dict[str, Any]:
    """The masked structure of an OFD file, as plain data ready for JSON."""
    package = Package(source)
    try:
        return _describe(package)
    finally:
        package.close()


def mask(text: str) -> str:
    """Chinese characters become 字, digits 0, letters x or X; spacing and punctuation stay."""
    out = []
    for char in text:
        if char.isdigit():
            out.append("0")
        elif char.isascii() and char.isalpha():
            out.append("X" if char.isupper() else "x")
        elif char.isalpha():
            out.append("字")
        else:
            out.append(char)
    return "".join(out)


def _describe(package: Package) -> dict[str, Any]:
    entries = []
    parts: dict[str, Any] = {}
    budget = [MAX_ELEMENTS]
    for name in package.names:
        info = package._entries[name]
        entry: dict[str, Any] = {
            "name": _mask_path(name),
            "size": info.file_size,
            "compressed_size": info.compress_size,
            "compression": _COMPRESSION.get(info.compress_type, str(info.compress_type)),
            "utf8_name_flag": bool(info.flag_bits & 0x800),
        }
        if _entry_name(info) != info.filename:
            entry["name_decoded_from_legacy_encoding"] = True
        entries.append(entry)
        if not name.lower().endswith(".xml"):
            continue
        try:
            data = package.read(name)
            root, repaired = parse_xml_reporting(data, name)
        except OFDError as exc:
            parts[_mask_path(name)] = {"error": mask(str(exc))}
            continue
        parts[_mask_path(name)] = {
            "encoding": declared_encoding(data),
            "needed_repair": repaired,
            "root": _element(root, None, budget),
        }
    description = {
        "ofdkit_version": __version__,
        "note": "Text is masked: Chinese characters became 字, digits 0, letters x/X.",
        "entries": entries,
        "xml": parts,
    }
    if budget[0] < 0:
        description["truncated_elements"] = -budget[0]
    return description


def _element(element: ET.Element, parent_namespace: str | None, budget: list[int]) -> dict[str, Any] | None:
    budget[0] -= 1
    if budget[0] < 0:
        return None
    tag = element.tag if isinstance(element.tag, str) else ""
    namespace = tag[1:].split("}", 1)[0] if tag.startswith("{") else ""
    name = local_name(tag)
    node: dict[str, Any] = {"tag": name}
    if namespace != parent_namespace:
        node["ns"] = namespace
    if element.attrib:
        node["attrs"] = {local_name(key): _attribute(local_name(key), value) for key, value in element.attrib.items()}
    text = (element.text or "").strip()
    if text:
        node["text"] = _text(name, text)
    children = []
    for child in element:
        described = _element(child, namespace, budget)
        if described is None:
            break
        children.append(described)
    if children:
        node["children"] = children
    return node


def _text(element_name: str, text: str) -> str:
    kept = text if element_name in _STRUCTURAL_TEXT and _SAFE_TEXT.match(text) else mask(text)
    return kept if len(kept) <= _MAX_TEXT else kept[:_MAX_TEXT] + f"…(+{len(kept) - _MAX_TEXT})"


def _attribute(name: str, value: str) -> str:
    if name in _KEEP_ATTRIBUTES:
        return value
    if name in _TEXT_ATTRIBUTES or not _SAFE_ATTRIBUTE.match(value):
        return mask(value)
    return value if len(value) <= _MAX_TEXT else value[:_MAX_TEXT] + f"…(+{len(value) - _MAX_TEXT})"


def _mask_path(path: str) -> str:
    """Entry names keep their ASCII parts; other letters, which may spell a person's name, become 字."""
    return "".join(char if char.isascii() or not char.isalpha() else "字" for char in path)


_COMPRESSION = {zipfile.ZIP_STORED: "stored", zipfile.ZIP_DEFLATED: "deflated", zipfile.ZIP_BZIP2: "bzip2", zipfile.ZIP_LZMA: "lzma"}

__all__ = ["MAX_ELEMENTS", "OFDFormatError", "describe", "mask"]
