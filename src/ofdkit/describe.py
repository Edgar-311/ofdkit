"""Describe an OFD file's structure with its content masked, for bug reports.

The output shows the package entries, how each XML part is encoded and nested, and the
numbers that place things on the page, so a maintainer can rebuild the same structure
in a synthetic test file. Anything that could name a person or a company or hold an
invoice number is masked character by character (Chinese characters become 字, digits
0, letters x or X):

- element text, except coordinates, IDs and the locations listed below;
- attribute values, except numbers, coordinates and the keywords of the OFD format
  (``true``, ``Round``, ``Background`` ...), and except font names;
- entry names and the locations that point at them (``DocRoot``, ``FileLoc``,
  ``BaseLoc`` ...): the names the OFD layout itself uses, such as ``Doc_0``, ``Pages``
  or ``Content.xml``, are kept, every other part of a path is masked. The same name is
  masked the same way everywhere, so references can still be followed; names that
  would mask alike are told apart with ``~2``, ``~3``;
- element and attribute names that are not plain identifiers;
- any run of seven or more digits, even inside a number list.

Images, fonts and other binary parts are listed by size only. Masking is a best
effort: people should still look through the output before sharing it.
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

NOTE = (
    "Masked: Chinese characters became 字, digits 0, letters x/X, in text, attribute values "
    "and file names. Kept: the OFD layout's own names, coordinates, IDs and format keywords. "
    "Please look through this file before sharing it."
)

# Elements whose text is a location inside the package (ST_Loc in GB/T 33190).
_LOCATION_ELEMENTS = {
    "DocRoot", "FileLoc", "PublicRes", "DocumentRes", "PageRes", "CustomTags", "Annotations",
    "Attachments", "Extensions", "Signatures", "MediaFile", "FontFile", "SignedValue", "BaseLoc",
    "Thumbnail", "CoverPage",
}
# Elements whose text is numbers: boxes, IDs, path data, versions.
_NUMBER_ELEMENTS = {
    "PhysicalBox", "ApplicationBox", "ContentBox", "BleedBox", "CropBox", "ObjectRef", "MaxUnitID",
    "AbbreviatedData", "Version", "DocType",
}
# Attributes whose values are names or free text, masked even when they look harmless.
_TEXT_ATTRIBUTES = {"Name", "Title", "FileName", "Creator", "Author", "Subject", "Value", "Company", "ProviderName"}
# Font names help with font problems and are never personal data: kept as they are.
_KEEP_ATTRIBUTES = {"FontName", "FamilyName"}
# Keywords of the OFD format that attribute values take; any other word is masked.
_KEYWORDS = {
    word.casefold()
    for word in (
        "true false none ofd ofda round square butt miter bevel even-odd nonzero image body "
        "background foreground watermark header footer link path text composite highlight "
        "underline stamp signature xyz fit fith fitv fitr click mo mi seal sign normal bold "
        "italic dx dy gotoa uri sound movie"
    ).split()
}
# One item of a number list: a number, the "g" of DeltaX/DeltaY, or a colour such as #FF0000.
_NUMBER_ITEM = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?|[gG]|#[0-9A-Fa-f]{6,8}")
_PATH_DATA = re.compile(r"[MLQBACSZmlqbacsz\d\s.,+\-eE]*")
_LONG_NUMBER = re.compile(r"\d{7,}")
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_.\-]*")
# Words the OFD layout uses in entry names (Doc_0/Pages/Page_1/Content.xml, Res/font_3.ttf ...).
_LAYOUT_WORDS = {
    word.casefold()
    for word in (
        "ofd doc document documentres content page pages res publicres pageres signs sign "
        "signature signatures signedvalue signvalue seal annots annot annotation annotations "
        "tags tag customtag customtags tpls tpl template templates temp attachs attach "
        "attachments image images img font fonts media pic picture qrcode qr original invoice "
        "e-invoice kinggridtpls kinggridtpl ofdentries signfilepaths areaholderblocks "
        "extensions extension outlines bookmarks thumbnail cover versions version entries"
    ).split()
}
_LAYOUT_TOKEN = re.compile(r"(?i)(?:p\d{1,6}|([a-z\-]+?)?\d{0,6})")
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
    masker = _Masker()
    entries = []
    parts: dict[str, Any] = {}
    budget = [MAX_ELEMENTS]
    for name in package.names:
        info = package._entries[name]
        entry: dict[str, Any] = {
            "name": masker.path(name),
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
            parts[masker.path(name)] = {"error": mask(str(exc))}
            continue
        parts[masker.path(name)] = {
            "encoding": declared_encoding(data),
            "needed_repair": repaired,
            "root": _element(root, None, budget, masker),
        }
    description = {"ofdkit_version": __version__, "note": NOTE, "entries": entries, "xml": parts}
    if budget[0] < 0:
        description["truncated_elements"] = -budget[0]
    return description


class _Masker:
    """Masks locations the same way everywhere, so references can still be followed."""

    def __init__(self) -> None:
        self._components: dict[str, str] = {}
        self._used: set[str] = set()

    def path(self, path: str) -> str:
        return "".join(part if part in ("/", "\\") else self.component(part) for part in re.split(r"([/\\])", path))

    def component(self, component: str) -> str:
        if component in ("", ".", ".."):
            return component
        if component not in self._components:
            stem, extension = _split_extension(component)
            if _is_layout_name(stem):
                masked = component
            else:
                masked = mask(stem) + extension
                number = 1
                while masked in self._used:
                    number += 1
                    masked = f"{mask(stem)}~{number}{extension}"
            self._components[component] = masked
            self._used.add(masked)
        return self._components[component]


def _split_extension(component: str) -> tuple[str, str]:
    stem, dot, extension = component.rpartition(".")
    if dot and stem and re.fullmatch(r"[A-Za-z0-9]{1,5}", extension) and re.search(r"[A-Za-z]", extension):
        return stem, "." + extension
    return component, ""


def _is_layout_name(stem: str) -> bool:
    """True for names such as Doc_0, Page_12, font_3_1, P1_Image_2 or original_invoice."""
    tokens = [token for token in re.split(r"[_]", stem) if token]
    if not tokens:
        return False
    for token in tokens:
        match = _LAYOUT_TOKEN.fullmatch(token)
        if not match or (match.group(1) and match.group(1).casefold() not in _LAYOUT_WORDS):
            return False
    return True


def _element(element: ET.Element, parent_namespace: str | None, budget: list[int], masker: _Masker) -> dict[str, Any] | None:
    budget[0] -= 1
    if budget[0] < 0:
        return None
    tag = element.tag if isinstance(element.tag, str) else ""
    namespace = tag[1:].split("}", 1)[0] if tag.startswith("{") else ""
    name = local_name(tag)
    node: dict[str, Any] = {"tag": _name(name)}
    if namespace != parent_namespace:
        node["ns"] = namespace
    if element.attrib:
        node["attrs"] = {
            _name(local_name(key)): _attribute(local_name(key), value, masker) for key, value in element.attrib.items()
        }
    text = (element.text or "").strip()
    if text:
        node["text"] = _text(name, text, masker)
    children = []
    for child in element:
        described = _element(child, namespace, budget, masker)
        if described is None:
            break
        children.append(described)
    if children:
        node["children"] = children
    return node


def _text(element_name: str, text: str, masker: _Masker) -> str:
    if element_name in _LOCATION_ELEMENTS:
        kept = masker.path(text)
    elif element_name in _NUMBER_ELEMENTS and _PATH_DATA.fullmatch(text) and not _LONG_NUMBER.search(text):
        kept = text
    elif element_name == "DocType" and text.casefold() in _KEYWORDS:
        kept = text
    else:
        kept = mask(text)
    return _shorten(kept)


def _attribute(name: str, value: str, masker: _Masker) -> str:
    if name in _KEEP_ATTRIBUTES:
        return _shorten(value)
    if name in _TEXT_ATTRIBUTES:
        return _shorten(mask(value))
    if name.endswith("Loc") or name == "FileRef" or "/" in value or "\\" in value:
        return _shorten(masker.path(value))
    if _is_number_list(value) or value.casefold() in _KEYWORDS:
        return _shorten(value)
    return _shorten(mask(value))


def _is_number_list(text: str) -> bool:
    if _LONG_NUMBER.search(text):  # checked first: it also keeps the item pattern fast
        return False
    return all(_NUMBER_ITEM.fullmatch(item) for item in re.split(r"[\s,]+", text) if item)


def _name(name: str) -> str:
    """Element and attribute names: plain identifiers stay, anything else is masked."""
    return name if _IDENTIFIER.fullmatch(name) and not _LONG_NUMBER.search(name) else mask(name)


def _shorten(text: str) -> str:
    return text if len(text) <= _MAX_TEXT else text[:_MAX_TEXT] + f"…(+{len(text) - _MAX_TEXT})"


_COMPRESSION = {zipfile.ZIP_STORED: "stored", zipfile.ZIP_DEFLATED: "deflated", zipfile.ZIP_BZIP2: "bzip2", zipfile.ZIP_LZMA: "lzma"}

__all__ = ["MAX_ELEMENTS", "NOTE", "OFDFormatError", "describe", "mask"]
