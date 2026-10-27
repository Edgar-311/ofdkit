# AGENTS.md

Instructions for AI coding agents (Claude, Codex and others) working on this repository.
Read this file first; it carries the context between sessions.

## What this project is

ofdkit reads OFD documents (GB/T 33190, China's fixed-layout format used for e-invoices
and official documents) and makes their content usable by programs and AI tools.

Scope, all read-only:

- Text extraction in reading order, as plain text and Markdown
- Invoice fields from e-invoices (数电票 and older 增值税电子发票): invoice number, issue
  date, buyer and seller, amounts, tax, total, line items, as JSON
- CLI for people (`ofdkit PATH`, Chinese output) and for programs (JSON, CSV); folders
  and ZIP archives of invoices summarised as an Excel workbook or CSV
- AI integrations: an MCP server, an Agent Skill, and a MarkItDown plugin

Out of scope: converting OFD to PDF or images, writing or editing OFD, and OCR.

Companion repository: [ofd-samples](https://github.com/Edgar-311/ofd-samples), a public
set of synthetic OFD test files with expected outputs.

## Rules that are never relaxed

1. Read only. Never write code that creates or modifies an invoice, and never create test
   files that look like an invoice. Invoice-field tests use plain documents that carry the
   same structure (custom tags) without any invoice layout.
2. No real invoices or personal data in this repository: not in tests, fixtures, issues
   or docs. If a user shares a real file to report a bug, reproduce the structure with a
   synthetic file and do not commit theirs.
3. Be honest about AI involvement. The README says the code is AI-assisted. Commits name
   the maintainer as author because they direct and own the work, and every commit made
   by an agent keeps the `Co-Authored-By` trailer naming the agent. Never remove that
   trailer, and never claim anywhere (README, posts, applications) that the maintainer
   wrote the code by hand.
4. No growth hacking: no star exchanges, no unsolicited promotion in other projects, no
   bulk low-value pull requests to other repositories.
5. Releases to PyPI happen only after the maintainer explicitly approves (they reply "发").
   Anything public (posts, comments, PRs to other projects) also needs their approval.

## Working with the maintainer

The maintainer is Edgar-311, the repository owner. Write to them in simple Chinese:
short sentences, and explain technical terms the first time they appear. Ask before
anything public or irreversible; otherwise make sensible decisions and report them.

## Development

- Python 3.10 or newer. The core has no runtime dependencies: use only the standard
  library (zipfile, xml.etree.ElementTree). Optional extras may add dependencies for
  integrations (MCP, MarkItDown).
- Layout: `src/ofdkit/` for the package, `tests/` for unittest tests.
- Set up: `uv venv && uv pip install -e .`
- Test: `python -m unittest discover -s tests -t . -v`
- Build: `uv build`
- CI runs the tests on Linux (3.10, 3.12, 3.14), Windows and macOS (3.12), and again on
  Linux and Windows with the `mcp` and `markitdown` extras installed. Tests for the extras
  skip themselves when the extra is missing. Keep paths and text encodings
  platform-neutral: always open text files with `encoding="utf-8"`.
- The MCP server uses the official `mcp` SDK (2.x, `MCPServer`) instead of a hand-written
  protocol: the protocol gained a new request format in revision 2026-07-28, and the SDK
  negotiates both that and the older initialize handshake. `tests/test_mcp.py` checks
  the handshake over real stdio.
- `tests/test_samples.py` checks ofdkit against the expected outputs in ofd-samples. It
  runs when `OFD_SAMPLES_DIR` points at a checkout (CI does this) or `../ofd-samples`
  exists. When a bug is found in a real file, add a synthetic sample with the same
  structure to ofd-samples first, then fix ofdkit.
- Language: what the command line prints for people (help, messages, `show`, the batch
  summary, the Excel headers) is Chinese, because OFD users read Chinese. Library
  exceptions, JSON keys, CSV columns and MCP descriptions stay English for programs;
  `batch.problems()` turns the known messages into Chinese for people.
- `xlsx.py` writes Excel files by hand (no dependency). CI's extras job installs
  openpyxl to read them back; for layout changes, also open one in LibreOffice
  (`soffice --headless --convert-to html`) and look at it.
- Every behaviour change comes with a test.

## Commits

- Author: `Edgar-311 <347874636+Edgar-311@users.noreply.github.com>`, GitHub's no-reply
  address for the maintainer. Never use a personal email address. The committer is the
  agent. In a fresh clone, set this once:
  `git config author.name Edgar-311`
  `git config author.email 347874636+Edgar-311@users.noreply.github.com`
- End every commit message with the agent's `Co-Authored-By` trailer.
- Never rewrite or force-push published history.

## Releasing

Only after the maintainer replies "发" (rule 5).

1. Move the `[Unreleased]` notes in CHANGELOG.md under a new `[X.Y.Z] - YYYY-MM-DD`
   heading and set `version = "X.Y.Z"` in pyproject.toml. Commit and push; wait for CI.
2. Agent sessions cannot create GitHub releases (the API returns 403), so the maintainer
   publishes it: give them a prefilled link,
   `https://github.com/Edgar-311/ofdkit/releases/new?tag=vX.Y.Z&target=main&title=vX.Y.Z&body=<url-encoded notes>`,
   and ask them to click "Publish release". Then watch the Release workflow run.
3. `.github/workflows/release.yml` checks the tag against the version, runs the tests,
   builds, and uploads to PyPI through Trusted Publishing (environment `pypi`). Its last
   job lists the version in the official MCP Registry (`server.json`, name
   `io.github.Edgar-311/ofdkit`, GitHub OIDC login, no secrets). The registry checks for
   the `mcp-name:` line at the top of README.md; never remove it.
4. Set the version to the next `.dev0` (for example `0.4.0.dev0`) afterwards.

PyPI side (one-time, done by the maintainer in their PyPI account): a trusted publisher
for project `ofdkit`, owner `Edgar-311`, repository `ofdkit`, workflow `release.yml`,
environment `pypi`.

## Status

- [x] Repository, license (Apache-2.0), package skeleton, CI
- [x] OFD container and document model (OFD.xml, Document.xml, pages, templates,
      composite graphic units), tolerant of the producer bugs listed in `_xml.py` and
      `package.py`
- [x] Text extraction in reading order (`layout.py`)
- [x] Invoice fields from XML attachments, custom tags and OFD.xml CustomData (`invoice.py`)
- [x] CLI commands: show (also `ofdkit PATH`), info, text, invoice, batch, rename,
      describe (`cli.py`, `report.py`); batch writes an Excel workbook (`xlsx.py`) or
      UTF-8 CSV with a BOM, reads ZIP archives (`batch.py`), flags duplicate invoices and,
      with `--buyer`, invoices for another buyer
- [x] `ofdkit rename` (`rename.py`): preview by default, `--apply`, `--undo` from the log;
      never overwrites. It is the only command that changes the user's files; keep it
      that way, keep its preview-first default, and keep the log written (and synced)
      before each rename
- [x] `--buyer` check, `ofdkit rename`, `py.typed`; 0.3.0 released to PyPI on 2026-10-28
- [x] Listed in the official MCP Registry as `io.github.Edgar-311/ofdkit` since 0.3.1
      (2026-10-28); every release updates the listing
- [x] Markdown output and MarkItDown plugin (`markdown.py`, `markitdown_plugin.py`)
- [x] MCP server (`mcp_server.py`, `ofdkit mcp`): read_ofd_text, read_ofd_invoice,
      ofd_info, list_ofd_invoices; all read-only, optional `--root` folder restriction.
      `--root` goes through `_guard.PathGuard`: every file is checked by its real path
      right before it is opened. Any new tool that opens files must use it too
- [x] Agent Skill (`skills/ofd-reader/SKILL.md`, format checked by `tests/test_skill.py`)
- [x] v0.1.0 released to PyPI on 2026-10-26 (https://pypi.org/project/ofdkit/)
- [x] Better reading order (vertical labels, prose columns), `invoice_type`,
      `ofdkit describe`, GitHub issue forms, Excel output, ZIP archives, `ofdkit show`,
      Chinese CLI, `ofdkit.read_invoices`; 0.2.0 released to PyPI on 2026-10-27

Known gaps, in rough order of value:

- Reading order is heuristic (`layout.py` explains the steps and thresholds). Known
  misses: complex magazine layouts with three or more columns around pictures, vertical
  labels whose characters sit more than 3 font sizes apart (备注 on some older invoices),
  and rotated text.
- Text drawn as vector paths or images has no text to extract; that needs OCR, which is
  out of scope.

## Checking against real files

Real OFD files must never be committed (rule 2). For local checks, public test files
from Apache-2.0 projects such as [ofdrw](https://github.com/ofdrw/ofdrw) can be fetched
into a scratch directory outside the repository:

    git clone --depth 1 --filter=blob:none --no-checkout https://github.com/ofdrw/ofdrw
    git -C ofdrw sparse-checkout set --no-cone '*.ofd' && git -C ofdrw checkout

Then open every file with ofdkit and check that all open, that text runs fall inside
their page boxes, and that invoices yield fields. Last run: 77 files, all opened.
