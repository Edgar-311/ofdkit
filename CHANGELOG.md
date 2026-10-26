# Changelog

所有重要的变化都记录在这里。格式参考 [Keep a Changelog](https://keepachangelog.com/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。
Notable changes are recorded here, following [Keep a Changelog](https://keepachangelog.com/) and [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.2.0] - 2026-10-26

### Added

- `ofdkit describe`: the file's structure as JSON with all text masked (Chinese
  characters become 字, digits 0, letters x/X), so problems can be reported without
  sharing an invoice. GitHub issue forms ask for it instead of the file.
- `invoice_type`: the invoice type as printed in its title, such as
  电子发票（增值税专用发票） or 上海增值税电子普通发票, in the JSON, the CSV from
  `batch` and the Markdown table.

### Changed

- Better reading order. Vertical labels written one character per line, such as
  购买方信息 and 备注 on e-invoices, are read as words instead of being scattered over
  the lines beside them. Pages with columns of prose are read column by column; tables
  are still read row by row.
- The CSV from `batch` has a new `invoice_type` column after `invoice_code`.

### Fixed

- The MCP tool `read_ofd_text` with a page range no longer fails when one page in the
  range is damaged; that page is marked and the others are returned.

## [0.1.0] - 2026-10-26

First release.

### Added

- Read OFD documents (GB/T 33190) with only the Python standard library: pages,
  templates, page blocks and composite graphic units, tolerant of common producer bugs
  (absolute or wrongly cased paths, GBK names and encodings, broken XML prefixes).
- Text extraction in reading order, as plain text or Markdown.
- Invoice fields from e-invoices (数电票 and 增值税电子发票), from XML attachments,
  custom tags and OFD.xml metadata, with amounts and dates normalised and a warning when
  totals do not add up.
- Command line: `ofdkit info`, `text`, `invoice`, `batch` (CSV for Excel, duplicate
  invoice numbers flagged) and `mcp`.
- MCP server for AI tools (`pip install "ofdkit[mcp]"`), read-only, with an optional
  folder restriction.
- MarkItDown plugin (`pip install "ofdkit[markitdown]"`).
- The `ofd-reader` Agent Skill.

[Unreleased]: https://github.com/Edgar-311/ofdkit/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/Edgar-311/ofdkit/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Edgar-311/ofdkit/releases/tag/v0.1.0
