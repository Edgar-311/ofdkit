"""XML helpers: safe parsing, recovery from common producer bugs, namespace-free lookups.

OFD files in the wild use several namespace URIs (``http://www.ofdspec.org/2016``,
``http://www.ofdspec.org``, the e-invoice schemas, or none at all), and some producers
write malformed XML such as ``<:eInvoice xmlns:="">`` or undeclared prefixes. All lookups
here therefore match on local names only, and parsing falls back to a repaired copy of
the text when strict parsing fails.
"""

from __future__ import annotations

import codecs
import re
import xml.etree.ElementTree as ET
from collections.abc import Iterator

from .errors import OFDFormatError, OFDLimitError

# OFD never needs a DTD; refusing them rules out entity-expansion attacks.
_FORBIDDEN = re.compile(r"<!DOCTYPE|<!ENTITY", re.IGNORECASE)
_DECLARED_ENCODING = re.compile(rb"""^\s*<\?xml[^>]*?encoding\s*=\s*["']([A-Za-z0-9._-]+)["']""")
_XML_DECLARATION = re.compile(r"^\s*<\?xml[^>]*\?>")
_TAG = re.compile(r"<[^<>]*>")
_ELEMENT_PREFIX = re.compile(r"^<(/?)[^\s<>/=\"':]*:")
_XMLNS_ATTRIBUTE = re.compile(r"""\s+xmlns(?::[^\s=]*)?\s*=\s*(?:"[^"]*"|'[^']*')""")
_ATTRIBUTE_PREFIX = re.compile(r"""(\s)[^\s<>/="':]+:(?=[^\s<>/="':]+\s*=)""")

# Chinese producers often declare GB2312 or GBK; GB18030 is a superset of both.
_ENCODING_ALIASES = {"gb2312": "gb18030", "gbk": "gb18030", "cp936": "gb18030"}


def local_name(tag: object) -> str:
    """Return the tag name without its namespace (comments and PIs give '')."""
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1]


def children(element: ET.Element, name: str) -> Iterator[ET.Element]:
    """Direct children with the given local name."""
    for child_element in element:
        if local_name(child_element.tag) == name:
            yield child_element


def grandchildren(element: ET.Element | None, container: str, name: str) -> Iterator[ET.Element]:
    """Children named ``name`` of the first child named ``container``, if any."""
    holder = child(element, container)
    if holder is not None:
        yield from children(holder, name)


def child(element: ET.Element | None, name: str) -> ET.Element | None:
    """First direct child with the given local name, or None."""
    if element is None:
        return None
    return next(children(element, name), None)


def child_text(element: ET.Element | None, name: str) -> str | None:
    """Stripped text of the first direct child with the given local name, or None."""
    found = child(element, name)
    if found is None or found.text is None:
        return None
    text = found.text.strip()
    return text or None


def parse_xml(data: bytes, name: str = "XML") -> ET.Element:
    """Parse an XML part strictly, falling back to a repaired copy for broken files."""
    return parse_xml_reporting(data, name)[0]


def parse_xml_reporting(data: bytes, name: str = "XML") -> tuple[ET.Element, bool]:
    """Like parse_xml, and also say whether the part needed repairing to parse."""
    try:
        text = _decode(data)
    except UnicodeError as exc:
        raise OFDFormatError(f"{name}: cannot decode XML: {exc}") from exc
    if _FORBIDDEN.search(text):
        raise OFDLimitError(f"{name}: DTDs and entity declarations are not allowed")
    text = _XML_DECLARATION.sub("", text, count=1)
    try:
        return ET.fromstring(text), False
    except ET.ParseError as first_error:
        try:
            return ET.fromstring(_repair(text)), True
        except ET.ParseError:
            raise OFDFormatError(f"{name}: invalid XML: {first_error}") from first_error


def declared_encoding(data: bytes) -> str | None:
    """The encoding named in the XML declaration, 'BOM:UTF-8'/'BOM:UTF-16' for a byte order mark, or None."""
    if data.startswith(codecs.BOM_UTF8):
        return "BOM:UTF-8"
    if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return "BOM:UTF-16"
    match = _DECLARED_ENCODING.match(data)
    return match.group(1).decode("ascii") if match else None


def _decode(data: bytes) -> str:
    if data.startswith(codecs.BOM_UTF8):
        return data[len(codecs.BOM_UTF8):].decode("utf-8", errors="replace")
    if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return data.decode("utf-16")
    declared = _DECLARED_ENCODING.match(data)
    if declared:
        encoding = declared.group(1).decode("ascii").lower()
        encoding = _ENCODING_ALIASES.get(encoding, encoding)
        try:
            codec_name = codecs.lookup(encoding).name
        except LookupError:  # unknown declaration: fall through to detection
            codec_name = "utf-8"
        if codec_name != "utf-8":
            return data.decode(codec_name, errors="replace")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        # Undeclared non-UTF-8 text from Chinese producers is almost always GBK.
        return data.decode("gb18030", errors="replace")


def _repair(text: str) -> str:
    """Drop namespace declarations and prefixes so that unbound or empty prefixes parse."""
    return _TAG.sub(_repair_tag, text)


def _repair_tag(match: re.Match[str]) -> str:
    tag = match.group(0)
    if tag.startswith(("<?", "<!")):
        return tag
    tag = _ELEMENT_PREFIX.sub(r"<\1", tag, count=1)
    tag = _XMLNS_ATTRIBUTE.sub("", tag)
    return _ATTRIBUTE_PREFIX.sub(r"\1", tag)
