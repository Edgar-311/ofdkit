---
name: ofd-reader
description: Read OFD files (GB/T 33190), the Chinese fixed-layout format used for e-invoices (电子发票, 数电票, 增值税电子发票) and official documents (公文). Use when the user mentions a .ofd file, asks to read, summarise or translate one, wants invoice fields (发票号码, 金额, 税额, 价税合计, 购买方, 销售方), wants a folder of invoices totalled or exported to Excel/CSV (发票汇总, 报销), wants invoice files renamed after their contents (发票重命名), or wants to check the buyer on invoices (发票抬头).
license: Apache-2.0
compatibility: Needs Python 3.10+ with uv (uvx) or pip, and network access to install ofdkit the first time.
---

# Reading OFD files with ofdkit

OFD files are ZIP packages of XML. Do not try to read them with a PDF tool or by
unzipping and guessing; use the `ofdkit` command line, which handles the format and
many broken files.

## Running ofdkit

Prefer `uvx`, which needs no installation step:

```bash
uvx ofdkit --version
```

If `uvx` is missing, install once with `pip install ofdkit` and call `ofdkit ...` (or
`python -m ofdkit ...`). If neither works, tell the user that ofdkit needs Python 3.10+
and either uv or pip.

## Tasks

| The user wants | Run |
| --- | --- |
| The text of a document | `uvx ofdkit text FILE.ofd` |
| Text for summarising or translating, with an invoice table for e-invoices | `uvx ofdkit text FILE.ofd --markdown` |
| The fields of one invoice | `uvx ofdkit invoice FILE.ofd` (JSON) |
| A spreadsheet of all invoices in a folder or .zip archive, for the user | `uvx ofdkit batch FOLDER -o 发票汇总.xlsx` (add `-r` for subfolders) |
| The same as data for you to process | `uvx ofdkit batch FOLDER` (CSV on stdout, totals on stderr) |
| A quick look at an invoice or a folder, in Chinese | `uvx ofdkit show PATH` |
| Check that invoices are made out to their company (发票抬头) | add `--buyer NAME --buyer TAX_ID` to `show` or `batch` |
| Rename invoice files after their contents | `uvx ofdkit rename FOLDER` (preview), then `--apply` |
| Page count, size, author, whether it is an invoice | `uvx ofdkit info FILE.ofd --json` |

Exit codes: `0` success, `1` the file holds no invoice data (`invoice` command only; try
`text` instead), `2` the file could not be read (the message on stderr says why).

## Working with the results

- Amounts are decimal strings. Add them with exact decimal arithmetic, not floats.
  `batch` prints the totals on stderr, also without duplicates.
- Check `warnings`: they report totals that do not add up and duplicate invoices (the
  same invoice number, and the same invoice code for older invoices, in several files:
  the same invoice submitted twice). Point these out to the user.
- `issue_date` is `YYYY-MM-DD` when the date could be read; otherwise it is the text as
  printed.
- When the user wants a spreadsheet, write `.xlsx`, not `.csv`: Excel turns long invoice
  numbers in a CSV into numbers like 2.4E+19. The workbook keeps them as text, has
  totals, flags duplicates, and lists line items on a second sheet. Rows that are not
  invoices have the reason in the `error` column (CSV) or 提醒 (Excel).
- `rename` changes the user's files. Run it without `--apply` first, show the user the
  preview, and add `--apply` only after they agree. It prints the `--undo` command for
  going back; tell the user about it.
- `batch` and `show` read .zip archives as folders, so an archive downloaded from the
  tax service does not need unzipping first.
- ofdkit reports what a file contains. It does not verify that an invoice is genuine;
  say so if the user asks whether an invoice is real, and point them to the official
  verification service of the State Taxation Administration (国家税务总局全国增值税发票查验平台).
- Text drawn as images or vector shapes cannot be extracted. If `text` returns little or
  nothing for a file that clearly has content, the file is probably a scan.
- If ofdkit reads a file wrongly, suggest reporting it with `uvx ofdkit describe FILE.ofd
  -o structure.json`, which masks all text, at https://github.com/Edgar-311/ofdkit/issues.
  Never upload the user's real file anywhere.

## Privacy

Invoices contain names, tax IDs, addresses and bank accounts. Process them locally, do
not upload them to other services, and only quote the fields the user needs.
