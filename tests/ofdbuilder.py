"""Build small synthetic OFD files for tests.

Only plain documents: no invoice layouts and no real data (see AGENTS.md). Invoice tests
reuse the custom tag structure with obviously fake values on an otherwise empty page.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass, field
from xml.sax.saxutils import escape

OFD_NS = "http://www.ofdspec.org/2016"


@dataclass
class Text:
    """A text object whose first glyph's baseline starts at (x, y), in millimetres."""

    text: str
    x: float
    y: float
    size: float = 4.0
    id: int | None = None
    delta_x: str | None = None


@dataclass
class OFDBuilder:
    namespace: str | None = OFD_NS
    page_size: tuple[float, float] = (210.0, 297.0)
    absolute_paths: bool = False
    title: str = "测试样例"
    custom_data: dict[str, str] = field(default_factory=dict)
    _next_id: int = 1000

    def tag(self, name: str) -> str:
        return f"ofd:{name}" if self.namespace else name

    def element(self, name: str, body: str = "", attributes: str = "", root: bool = False) -> str:
        if root and self.namespace:
            attributes = f'xmlns:ofd="{self.namespace}" {attributes}'.strip()
        attributes = f" {attributes}" if attributes else ""
        return f"<{self.tag(name)}{attributes}>{body}</{self.tag(name)}>"

    def text_object(self, text: Text) -> str:
        object_id = text.id if text.id is not None else self._new_id()
        boundary = f"{text.x} {text.y - text.size} {max(len(text.text), 1) * text.size} {text.size * 1.25}"
        code_attributes = f'X="0" Y="{text.size}"'
        if text.delta_x:
            code_attributes += f' DeltaX="{text.delta_x}"'
        code = self.element("TextCode", escape(text.text), code_attributes)
        return self.element("TextObject", code, f'ID="{object_id}" Boundary="{boundary}" Font="1" Size="{text.size}"')

    def content(self, texts: list[Text], before: str = "") -> bytes:
        objects = "".join(self.text_object(text) for text in texts)
        layer = self.element("Layer", objects, f'ID="{self._new_id()}"')
        return _xml(self.element("Page", before + self.element("Content", layer), root=True))

    def parts(
        self,
        pages: list[list[Text]],
        *,
        template: list[Text] | None = None,
        custom_tag: str | None = None,
        attachment: tuple[str, str] | None = None,
    ) -> dict[str, bytes]:
        """All parts of the package, by entry name. Tests may edit them before zipping."""
        e = self.element
        prefix = "/Doc_0/" if self.absolute_paths else ""
        width, height = self.page_size
        parts: dict[str, bytes] = {}

        datas = "".join(e("CustomData", escape(value), f'Name="{escape(name)}"') for name, value in self.custom_data.items())
        info = e("DocID", "test") + e("Title", escape(self.title)) + (e("CustomDatas", datas) if datas else "")
        doc_root = "/Doc_0/Document.xml" if self.absolute_paths else "Doc_0/Document.xml"
        body = e("DocBody", e("DocInfo", info) + e("DocRoot", doc_root))
        parts["OFD.xml"] = _xml(e("OFD", body, 'Version="1.0" DocType="OFD"', root=True))

        common = e("PageArea", e("PhysicalBox", f"0 0 {width} {height}")) + e("PublicRes", "PublicRes.xml")
        page_template = ""
        if template is not None:
            common += f'<{self.tag("TemplatePage")} ID="1" BaseLoc="{prefix}Tpls/Tpl_0/Content.xml"/>'
            parts["Doc_0/Tpls/Tpl_0/Content.xml"] = self.content(template)
            page_template = f'<{self.tag("Template")} TemplateID="1" ZOrder="Background"/>'

        page_list = ""
        for index, texts in enumerate(pages):
            page_list += f'<{self.tag("Page")} ID="{index + 1}" BaseLoc="{prefix}Pages/Page_{index}/Content.xml"/>'
            parts[f"Doc_0/Pages/Page_{index}/Content.xml"] = self.content(texts, before=page_template)

        extras = ""
        if custom_tag is not None:
            extras += e("CustomTags", "Tags/CustomTags.xml")
            tag = e("CustomTag", e("FileLoc", "CustomTag.xml"), 'TypeID="test"')
            parts["Doc_0/Tags/CustomTags.xml"] = _xml(e("CustomTags", tag, root=True))
            parts["Doc_0/Tags/CustomTag.xml"] = _xml(custom_tag)
        if attachment is not None:
            name, data = attachment
            extras += e("Attachments", "Attachs/Attachments.xml")
            item = e("Attachment", e("FileLoc", name), f'ID="{self._new_id()}" Name="data" Format="xml"')
            parts["Doc_0/Attachs/Attachments.xml"] = _xml(e("Attachments", item, root=True))
            parts[f"Doc_0/Attachs/{name}"] = _xml(data)

        parts["Doc_0/Document.xml"] = _xml(e("Document", e("CommonData", common) + e("Pages", page_list) + extras, root=True))
        font = f'<{self.tag("Font")} ID="1" FontName="宋体" FamilyName="宋体"/>'
        parts["Doc_0/PublicRes.xml"] = _xml(e("Res", e("Fonts", font), root=True))
        return parts

    def build(self, pages: list[list[Text]], **kwargs: object) -> bytes:
        return zip_parts(self.parts(pages, **kwargs))  # type: ignore[arg-type]

    def _new_id(self) -> int:
        self._next_id += 1
        return self._next_id


def zip_parts(parts: dict[str, bytes], gbk_names: bool = False) -> bytes:
    """Zip parts into an OFD package; ``gbk_names`` stores names as GBK without the UTF-8 flag."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in parts.items():
            info = _GBKZipInfo(name) if gbk_names else zipfile.ZipInfo(name)
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
    return buffer.getvalue()


class _GBKZipInfo(zipfile.ZipInfo):
    """Writes the entry name as GBK bytes, the way some Chinese tools do."""

    def _encodeFilenameFlags(self) -> tuple[bytes, int]:  # noqa: N802 - overrides zipfile
        return self.filename.encode("gbk"), self.flag_bits & ~0x800


def _xml(body: str) -> bytes:
    return ('<?xml version="1.0" encoding="UTF-8"?>' + body).encode("utf-8")
