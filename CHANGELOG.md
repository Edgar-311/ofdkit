# Changelog

所有重要的变化都记录在这里。格式参考 [Keep a Changelog](https://keepachangelog.com/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。
Notable changes are recorded here, following [Keep a Changelog](https://keepachangelog.com/) and [Semantic Versioning](https://semver.org/).

## [Unreleased]

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
