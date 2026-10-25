"""Document model: OFD.xml, Document.xml, pages, templates and text objects."""

from __future__ import annotations

import math
import unicodedata
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ._xml import child, child_text, children, grandchildren, local_name
from .errors import OFDError, OFDFormatError
from .layout import page_text
from .package import Package, Source

if TYPE_CHECKING:
    from .invoice import Invoice

#: Page box used when a file does not give one: A4 portrait, in millimetres.
DEFAULT_PAGE_BOX = (0.0, 0.0, 210.0, 297.0)
#: Deepest nesting of PageBlock and CompositeObject elements that is followed.
MAX_NESTING = 32
#: Text may stick out of the page box by this much (mm) and still count as on the page.
_PAGE_MARGIN = 2.0

# An affine transform (a, b, c, d, e, f): x' = a*x + c*y + e, y' = b*x + d*y + f.
Affine = tuple[float, float, float, float, float, float]
_IDENTITY: Affine = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


@dataclass(frozen=True)
class DocInfo:
    """Document metadata from OFD.xml (DocBody/DocInfo)."""

    doc_id: str | None = None
    title: str | None = None
    author: str | None = None
    subject: str | None = None
    abstract: str | None = None
    creation_date: str | None = None
    mod_date: str | None = None
    creator: str | None = None
    creator_version: str | None = None
    keywords: tuple[str, ...] = ()
    custom_data: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "title": self.title,
            "author": self.author,
            "subject": self.subject,
            "abstract": self.abstract,
            "creation_date": self.creation_date,
            "mod_date": self.mod_date,
            "creator": self.creator,
            "creator_version": self.creator_version,
            "keywords": list(self.keywords),
            "custom_data": dict(self.custom_data),
        }


@dataclass(frozen=True)
class TextRun:
    """A piece of text as placed on a page.

    Coordinates are in millimetres with the origin at the top left of the page.
    ``y`` is the baseline. ``width`` is an estimate of the advance width.
    """

    text: str
    x: float
    y: float
    size: float
    width: float
    object_id: str | None = None
    from_template: bool = False


class Page:
    """One page of an OFD document. Content is read on first use."""

    def __init__(self, document: OFDDocument, body: _Body, index: int, page_id: str | None, location: str | None) -> None:
        self._document = document
        self._body = body
        self.index = index
        self.id = page_id
        self.location = location
        self._box: tuple[float, float, float, float] | None = None
        self._runs: list[TextRun] | None = None
        self._objects: dict[str, str] | None = None

    @property
    def box(self) -> tuple[float, float, float, float]:
        """The page's physical box ``(x, y, width, height)`` in millimetres."""
        self._load()
        assert self._box is not None
        return self._box

    @property
    def width(self) -> float:
        return self.box[2]

    @property
    def height(self) -> float:
        return self.box[3]

    @property
    def runs(self) -> list[TextRun]:
        """All text runs on the page, including those from templates."""
        self._load()
        assert self._runs is not None
        return list(self._runs)

    def text(self) -> str:
        """The page's visible text in reading order."""
        x0, y0, width, height = self.box
        visible = [
            run
            for run in self.runs
            if x0 - _PAGE_MARGIN <= run.x <= x0 + width + _PAGE_MARGIN
            and y0 - _PAGE_MARGIN <= run.y <= y0 + height + _PAGE_MARGIN
        ]
        return page_text(visible)

    def object_text(self, object_id: str) -> str | None:
        """Text of the text object with this ID, wherever it sits on the page."""
        self._load()
        assert self._objects is not None
        return self._objects.get(object_id.strip())

    def _load(self) -> None:
        if self._runs is not None:
            return
        document = self._document
        runs: list[TextRun] = []
        objects: dict[str, str] = {}
        box = self._body.page_box
        if self.location is not None:
            root = document._package.read_xml(self.location)
            box = _parse_box(child_text(child(root, "Area"), "PhysicalBox")) or box
            units = document._composite_units(self._body)
            page_resources = [
                path
                for path in (document._package.resolve(self.location, (r.text or "")) for r in children(root, "PageRes"))
                if path is not None
            ]
            if page_resources:
                units = {**units, **document._load_units(page_resources)}
            for reference in children(root, "Template"):
                template = self._body.templates.get((reference.get("TemplateID") or "").strip())
                if template is not None:
                    template_runs, template_objects = document._template(template, units)
                    runs.extend(template_runs)
                    for object_id, text in template_objects.items():
                        objects.setdefault(object_id, text)
            page_runs, page_objects = _collect_text(root, units, from_template=False)
            runs.extend(page_runs)
            objects.update(page_objects)
        self._box, self._runs, self._objects = box, runs, objects

    def __repr__(self) -> str:
        return f"<Page index={self.index} id={self.id!r} location={self.location!r}>"


@dataclass
class _Body:
    """One DocBody of OFD.xml, resolved to entries in the package."""

    document_path: str
    page_box: tuple[float, float, float, float]
    templates: dict[str, str]
    resources: list[str]
    custom_tags: str | None
    attachments: str | None
    units: dict[str, ET.Element] | None = None


class OFDDocument:
    """An opened OFD file. Use :func:`ofdkit.open` to create one.

    Close it when done, or use it as a context manager.
    """

    def __init__(self, source: Source) -> None:
        self._package = Package(source)
        self._templates: dict[str, tuple[list[TextRun], dict[str, str]]] = {}
        self.warnings: list[str] = []
        try:
            self._load()
        except BaseException:
            self._package.close()
            raise

    def _load(self) -> None:
        entry = self._package.find("OFD.xml")
        if entry is None:
            raise OFDFormatError("not an OFD file: OFD.xml is missing")
        root = self._package.read_xml(entry)
        if local_name(root.tag) != "OFD":
            raise OFDFormatError(f"not an OFD file: OFD.xml has root <{local_name(root.tag)}>")
        bodies = list(children(root, "DocBody"))
        if not bodies:
            raise OFDFormatError("OFD.xml contains no DocBody")

        self.info = _parse_doc_info(child(bodies[0], "DocInfo"))
        self._bodies: list[_Body] = []
        self.pages: list[Page] = []
        for number, body in enumerate(bodies, start=1):
            location = child_text(body, "DocRoot")
            document_path = self._package.resolve(entry, location)
            if document_path is None:
                self.warnings.append(f"document {number}: DocRoot not found ({location})")
                continue
            self._load_body(document_path)
        if not self._bodies:
            raise OFDFormatError("no readable document in the file (Document.xml not found)")

    def _load_body(self, document_path: str) -> None:
        package = self._package
        document = package.read_xml(document_path)
        common = child(document, "CommonData")
        page_box = _parse_box(child_text(child(common, "PageArea"), "PhysicalBox")) or DEFAULT_PAGE_BOX
        templates: dict[str, str] = {}
        resources: list[str] = []
        if common is not None:
            for template in children(common, "TemplatePage"):
                template_id = (template.get("ID") or "").strip()
                resolved = package.resolve(document_path, template.get("BaseLoc"))
                if template_id and resolved is not None:
                    templates[template_id] = resolved
                elif template_id:
                    self.warnings.append(f"template {template_id}: not found ({template.get('BaseLoc')})")
            for element in common:
                if local_name(element.tag) in ("PublicRes", "DocumentRes"):
                    resolved = package.resolve(document_path, element.text)
                    if resolved is not None:
                        resources.append(resolved)
        body = _Body(
            document_path=document_path,
            page_box=page_box,
            templates=templates,
            resources=resources,
            custom_tags=package.resolve(document_path, child_text(document, "CustomTags")),
            attachments=package.resolve(document_path, child_text(document, "Attachments")),
        )
        self._bodies.append(body)
        for page in grandchildren(document, "Pages", "Page"):
            location = package.resolve(document_path, page.get("BaseLoc"))
            if location is None:
                self.warnings.append(f"page {len(self.pages) + 1}: content not found ({page.get('BaseLoc')})")
            page_id = (page.get("ID") or "").strip() or None
            self.pages.append(Page(self, body, len(self.pages), page_id, location))

    def _composite_units(self, body: _Body) -> dict[str, ET.Element]:
        if body.units is None:
            body.units = self._load_units(body.resources)
        return body.units

    def _load_units(self, resource_paths: list[str]) -> dict[str, ET.Element]:
        """Composite graphic units by ID, from resource files (PublicRes, DocumentRes, PageRes)."""
        units: dict[str, ET.Element] = {}
        for path in resource_paths:
            try:
                root = self._package.read_xml(path)
            except OFDError as exc:
                self.warnings.append(f"resources {path}: {exc}")
                continue
            for unit in grandchildren(root, "CompositeGraphicUnits", "CompositeGraphicUnit"):
                unit_id = (unit.get("ID") or "").strip()
                if unit_id:
                    units.setdefault(unit_id, unit)
        return units

    def _template(self, location: str, units: Mapping[str, ET.Element]) -> tuple[list[TextRun], dict[str, str]]:
        if location not in self._templates:
            try:
                root = self._package.read_xml(location)
            except OFDError as exc:
                self.warnings.append(f"template {location}: {exc}")
                self._templates[location] = ([], {})
            else:
                self._templates[location] = _collect_text(root, units, from_template=True)
        return self._templates[location]

    def page_by_id(self, page_id: str) -> Page | None:
        """The page with this ID (as used by PageRef in custom tags), or None."""
        page_id = page_id.strip()
        for page in self.pages:
            if page.id == page_id:
                return page
        return None

    def text(self, page_separator: str = "\n\n") -> str:
        """All pages' text in reading order. A page that cannot be read adds a warning."""
        texts = []
        for page in self.pages:
            try:
                texts.append(page.text())
            except OFDError as exc:
                self.warnings.append(f"page {page.index + 1}: {exc}")
                texts.append("")
        return page_separator.join(texts)

    def invoice(self) -> Invoice | None:
        """Invoice data if this file is an e-invoice, else None."""
        from .invoice import read_invoice

        return read_invoice(self)

    def close(self) -> None:
        self._package.close()

    def __enter__(self) -> OFDDocument:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"<OFDDocument pages={len(self.pages)}>"


def _parse_doc_info(element: ET.Element | None) -> DocInfo:
    if element is None:
        return DocInfo()
    keywords = tuple(
        keyword.text.strip()
        for keyword in grandchildren(element, "Keywords", "Keyword")
        if keyword.text and keyword.text.strip()
    )
    custom: dict[str, str] = {}
    for item in grandchildren(element, "CustomDatas", "CustomData"):
        name = (item.get("Name") or "").strip()
        if name:
            custom[name] = (item.text or "").strip()
    return DocInfo(
        doc_id=child_text(element, "DocID"),
        title=child_text(element, "Title"),
        author=child_text(element, "Author"),
        subject=child_text(element, "Subject"),
        abstract=child_text(element, "Abstract"),
        creation_date=child_text(element, "CreationDate"),
        mod_date=child_text(element, "ModDate"),
        creator=child_text(element, "Creator"),
        creator_version=child_text(element, "CreatorVersion"),
        keywords=keywords,
        custom_data=custom,
    )


def _collect_text(
    page_root: ET.Element, units: Mapping[str, ET.Element], *, from_template: bool
) -> tuple[list[TextRun], dict[str, str]]:
    """Text runs and object texts from a page or template Content.xml."""
    runs: list[TextRun] = []
    objects: dict[str, str] = {}

    def walk(elements: list[ET.Element], transform: Affine, depth: int) -> None:
        for element in elements:
            name = local_name(element.tag)
            if name == "TextObject":
                object_runs, text = _text_object(element, transform, from_template)
                runs.extend(object_runs)
                object_id = (element.get("ID") or "").strip()
                if object_id:
                    objects.setdefault(object_id, text)
            elif depth >= MAX_NESTING:
                continue
            elif name == "PageBlock":
                walk(list(element), transform, depth + 1)
            elif name == "CompositeObject":
                unit = units.get((element.get("ResourceID") or "").strip())
                content = child(unit, "Content")
                if content is not None:
                    walk(list(content), _compose(transform, _object_transform(element)), depth + 1)

    content = child(page_root, "Content")
    if content is not None:
        for layer in children(content, "Layer"):
            walk(list(layer), _IDENTITY, 0)
    return runs, objects


def _text_object(element: ET.Element, transform: Affine, from_template: bool) -> tuple[list[TextRun], str]:
    """Runs for each TextCode of a TextObject, plus the object's full text."""
    a, b, c, d, e, f = _compose(transform, _object_transform(element))
    size = _parse_float(element.get("Size"), 0.0)
    effective_size = size * (math.sqrt(abs(a * d - b * c)) or 1.0)
    x_scale = math.hypot(a, b) or 1.0
    object_id = (element.get("ID") or "").strip() or None

    runs: list[TextRun] = []
    texts: list[str] = []
    x = y = 0.0
    for code in children(element, "TextCode"):
        text = _clean(code.text)
        # A TextCode without X or Y reuses the previous TextCode's value.
        x = _parse_float(code.get("X"), x)
        y = _parse_float(code.get("Y"), y)
        texts.append(text)
        if not text:
            continue
        deltas = _parse_deltas(code.get("DeltaX"), len(text) - 1)
        runs.append(
            TextRun(
                text=text,
                x=a * x + c * y + e,
                y=b * x + d * y + f,
                size=effective_size,
                width=_advance(text, deltas, size) * x_scale,
                object_id=object_id,
                from_template=from_template,
            )
        )
    return runs, "".join(texts)


def _object_transform(element: ET.Element) -> Affine:
    """Object space to parent space: the CTM, then a move to the Boundary's origin."""
    box = _parse_box(element.get("Boundary")) or (0.0, 0.0, 0.0, 0.0)
    a, b, c, d, e, f = _parse_numbers(element.get("CTM"), 6) or _IDENTITY
    return (a, b, c, d, e + box[0], f + box[1])


def _compose(outer: Affine, inner: Affine) -> Affine:
    """The transform that applies ``inner`` first, then ``outer``."""
    A, B, C, D, E, F = outer
    a, b, c, d, e, f = inner
    return (A * a + C * b, B * a + D * b, A * c + C * d, B * c + D * d, A * e + C * f + E, B * e + D * f + F)


def _advance(text: str, deltas: list[float], size: float) -> float:
    """Advance width of ``text`` in object space, from DeltaX where given."""
    total = 0.0
    last = len(text) - 1
    for index, char in enumerate(text):
        if index < last and index < len(deltas):
            total += deltas[index]
        else:
            total += _char_width(char, size)
    return total


def _char_width(char: str, size: float) -> float:
    return size if unicodedata.east_asian_width(char) in ("W", "F") else size * 0.5


def _clean(text: str | None) -> str:
    """Drop control characters; tabs become spaces."""
    if not text:
        return ""
    return "".join(" " if char == "\t" else char for char in text if char == "\t" or unicodedata.category(char) != "Cc")


def _parse_float(value: str | None, default: float) -> float:
    if value is None:
        return default
    try:
        number = float(value)
    except ValueError:
        return default
    return number if math.isfinite(number) else default


def _parse_numbers(value: str | None, count: int) -> tuple[float, ...] | None:
    if not value:
        return None
    try:
        numbers = tuple(float(part) for part in value.replace(",", " ").split())
    except ValueError:
        return None
    if len(numbers) < count or not all(math.isfinite(n) for n in numbers[:count]):
        return None
    return numbers[:count]


def _parse_box(value: str | None) -> tuple[float, float, float, float] | None:
    numbers = _parse_numbers(value, 4)
    if numbers is None:
        return None
    return (numbers[0], numbers[1], numbers[2], numbers[3])


def _parse_deltas(value: str | None, limit: int) -> list[float]:
    """Parse a DeltaX/DeltaY list, expanding the ``g <count> <value>`` shorthand.

    Only the first ``limit`` values are kept, so a huge repeat count cannot use much memory.
    """
    if not value or limit <= 0:
        return []
    tokens = value.split()
    deltas: list[float] = []
    index = 0
    while index < len(tokens) and len(deltas) < limit:
        token = tokens[index]
        try:
            if token == "g" and index + 2 < len(tokens):
                count = int(float(tokens[index + 1]))
                delta = float(tokens[index + 2])
                deltas.extend([delta] * max(0, min(count, limit - len(deltas))))
                index += 3
                continue
            deltas.append(float(token))
        except (ValueError, OverflowError):
            pass
        index += 1
    return deltas
