# AGENTS.md

Instructions for AI coding agents (Claude, Codex and others) working on this repository.
Read this file first; it carries the context between sessions.

## What this project is

ofdkit reads OFD documents (GB/T 33190, China's fixed-layout format used for e-invoices
and official documents) and makes their content usable by programs and AI tools.

v0.1 scope, all read-only:

- Text extraction in reading order, as plain text and Markdown
- Invoice fields from e-invoices (数电票 and older 增值税电子发票): invoice number, issue
  date, buyer and seller, amounts, tax, total, line items, as JSON
- CLI: single file or a whole folder, folder results summarised as CSV
- AI integrations: an MCP server, an Agent Skill, and a MarkItDown plugin

Out of scope for v0.1: converting OFD to PDF or images, and writing or editing OFD.

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
- Every behaviour change comes with a test.

## Commits

- Author: `Edgar-311 <347874636+Edgar-311@users.noreply.github.com>`, GitHub's no-reply
  address for the maintainer. Never use a personal email address. The committer is the
  agent. In a fresh clone, set this once:
  `git config author.name Edgar-311`
  `git config author.email 347874636+Edgar-311@users.noreply.github.com`
- End every commit message with the agent's `Co-Authored-By` trailer.
- Never rewrite or force-push published history.

## Status

- [x] Repository, license (Apache-2.0), package skeleton, CI
- [x] OFD container and document model (OFD.xml, Document.xml, pages, templates,
      composite graphic units), tolerant of the producer bugs listed in `_xml.py` and
      `package.py`
- [x] Text extraction in reading order (`layout.py`)
- [x] Invoice fields from XML attachments, custom tags and OFD.xml CustomData (`invoice.py`)
- [x] CLI commands: info, text, invoice, batch (`cli.py`; batch writes UTF-8 CSV with a
      BOM for Excel and flags duplicate invoice numbers)
- [x] Markdown output and MarkItDown plugin (`markdown.py`, `markitdown_plugin.py`)
- [x] MCP server (`mcp_server.py`, `ofdkit mcp`): read_ofd_text, read_ofd_invoice,
      ofd_info, list_ofd_invoices; all read-only, optional `--root` folder restriction
- [x] Agent Skill (`skills/ofd-reader/SKILL.md`, format checked by `tests/test_skill.py`)
- [ ] v0.1.0 release

Known gaps, in rough order of value:

- Multi-column pages come out line by line across both columns (columns are separated
  by three spaces). Column detection would fix this.
- Vertical labels (one character per line, as on invoice templates) interleave with the
  text beside them.
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
