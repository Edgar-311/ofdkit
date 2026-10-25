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
3. Be honest about AI involvement. The README says the code is AI-assisted, and every
   commit made by an agent carries the co-author trailer. Never describe the maintainer as
   the author of code they did not write.
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
- Test: `python -m unittest discover -s tests -v`
- Build: `uv build`
- CI runs the tests on Linux (3.10, 3.12, 3.14), Windows and macOS (3.12). Keep paths and
  text encodings platform-neutral: always open text files with `encoding="utf-8"`.
- Every behaviour change comes with a test.

## Status

- [x] Repository, license (Apache-2.0), package skeleton, CI
- [ ] OFD container and document model (OFD.xml, Document.xml, pages, templates, resources)
- [ ] Text extraction in reading order
- [ ] Invoice fields via custom tags (Tags/CustomTags.xml)
- [ ] CLI commands: info, text, invoice, batch
- [ ] MCP server, Agent Skill, MarkItDown plugin
- [ ] v0.1.0 release
