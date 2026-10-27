# Changelog

所有重要的变化都记录在这里。格式参考 [Keep a Changelog](https://keepachangelog.com/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。
Notable changes are recorded here, following [Keep a Changelog](https://keepachangelog.com/) and [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- `ofdkit rename`: renames invoice files after their contents, by default as
  `{开票日期}_{销售方}_{价税合计}_{发票号码}.ofd`. It only previews until `--apply` is
  given, renames PDF and XML copies with the same name along with the OFD file, never
  overwrites a file (a clashing name gets ` (2)`), leaves files that already have their
  new name alone, and writes a log that `ofdkit rename --undo LOG` uses to restore the
  old names. `--pattern` sets the format from 13 fields, in Chinese or English.
- `--buyer NAME_OR_TAX_ID` for `show` and `batch`: flags invoices made out to another
  buyer (发票抬头), in the summary, the CSV `warnings` and in orange in Excel. The MCP
  tool `list_ofd_invoices` and `ofdkit.read_invoices()` take `buyer` too.
- `py.typed`, so type checkers use ofdkit's annotations.

## [0.2.0] - 2026-10-27

### Added

- Excel output: `ofdkit batch FOLDER -o 发票汇总.xlsx` writes a workbook, still with only
  the standard library. Invoice numbers, codes and tax IDs stay text (in a CSV, Excel
  turns a 20-digit 数电票 number into 2.4E+19), amounts are numbers and dates are
  dates. A totals row follows filters; duplicates and unreadable files are coloured
  and explained; a second sheet lists every line item.
- ZIP archives: `batch`, `show` and the MCP tool `list_ofd_invoices` read the `.ofd`
  files inside `.zip` archives, such as a batch download from the tax service.
- `ofdkit show`, and the shortcut `ofdkit PATH`: an invoice as aligned Chinese text,
  another document's text, or a table of the invoices in folders and archives with
  totals.
- `ofdkit.read_invoices()` reads files, folders and archives into `InvoiceFile`
  results.
- Totals without duplicates, and sums of amounts and tax, in the `batch` summary and
  `list_ofd_invoices`; an `item_names` column in the CSV.
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
- The CSV from `batch` has new `invoice_type` and `item_names` columns.
- Command-line help and messages are in Chinese. `text` and `show` say when a file has
  no text at all, which usually means a scan.

### Fixed

- Older invoices that share a number but have different invoice codes are no longer
  flagged as duplicates.
- Output piped into a program that stops reading early, such as `head`, no longer ends
  with an error.
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
