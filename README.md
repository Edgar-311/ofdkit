# ofdkit

<!-- mcp-name: io.github.Edgar-311/ofdkit -->

轻量的 Python 工具，用来读取 OFD 文件，提取里面的文字和发票字段，并能接入 AI 工具。OFD 是中国的国家标准版式文档格式（GB/T 33190），常见于电子发票和公文。

A lightweight Python toolkit for reading OFD documents (GB/T 33190, the Chinese fixed-layout format used for e-invoices and official documents): extract text and invoice fields, and use them from AI tools.

> 状态：0.3 版，接口以后可能还会调整。更新记录见 [CHANGELOG](https://github.com/Edgar-311/ofdkit/blob/main/CHANGELOG.md)。
> Status: 0.3, the API may still change. See the [CHANGELOG](https://github.com/Edgar-311/ofdkit/blob/main/CHANGELOG.md).

## 能做什么 / What it does

- 看发票：一条命令显示发票号码、日期、购买方、销售方、金额和明细。
  Show an invoice: number, date, buyer, seller, amounts and line items, with one command.
- 把一个文件夹里的发票汇总到 Excel，也能直接读税务平台批量下载的 .zip 压缩包。发票号码保持原样（不会变成 2.4E+19），金额可以直接求和，重复的发票会标出来。
  Summarise a folder of invoices, or a .zip archive downloaded from the tax service, into an Excel workbook: invoice numbers stay intact, amounts are numbers, duplicates are flagged.
- 报销帮手：检查发票抬头（购买方名称、税号）对不对；按发票内容给文件改名，可以预览、可以改回去。
  For reimbursement: check that invoices are made out to the right buyer, and rename invoice files after their contents, with a preview and an undo.
- 按阅读顺序提取文字，包括模板和复合对象里的文字。
  Text in reading order, including text in templates and composite objects.
- 给程序和 AI 用：发票字段输出 JSON，提供 MCP 服务器、Agent Skill 和 MarkItDown 插件。
  For programs and AI: invoice fields as JSON, an MCP server, an Agent Skill and a MarkItDown plugin.
- 只用 Python 标准库，没有任何第三方依赖；能读很多不规范的文件（路径写法不对、编码不对、XML 前缀错误等）。
  Standard library only, no dependencies; reads many non-conforming files (bad paths, encodings, XML prefixes).

## 快速上手 / Quick start

1. 安装 [Python](https://www.python.org/downloads/) 3.10 或更新版本。Windows 上安装时请勾选 "Add python.exe to PATH"。
   Install Python 3.10 or newer.
2. 打开命令行（Windows 在开始菜单搜索"终端"或"cmd"，Mac 打开"终端"），安装 ofdkit：
   Open a terminal and install ofdkit:

   ```bash
   pip install ofdkit
   ```

3. 看一张发票（把文件拖进命令行窗口就能填上路径）：
   Show an invoice (drag the file into the terminal window to type its path):

   ```bash
   ofdkit 发票.ofd
   ```

   ```text
   电子发票（普通发票）

   发票号码  00000000000000000001
   开票日期  2026-01-02
   购买方    测试单位甲
             税号 TESTBUYER0001
   销售方    测试单位乙
             税号 TESTSELLER0002
   金额      100.00
   税额      6.00
   价税合计  106.00
   明细      *测试*服务项目  100.00  6%
   开票人    测试人员
   ```

   （数据是虚构的 / fictional data）

4. 看一个文件夹或 .zip 压缩包里的所有发票和合计，然后导出到 Excel：
   List every invoice in a folder or .zip archive with totals, then export to Excel:

   ```bash
   ofdkit 发票文件夹
   ofdkit batch 发票文件夹 -o 发票汇总.xlsx
   ```

   Excel 文件有两张表："发票"每张发票一行，最后是合计；"明细"每个商品或服务一行。重复的发票标黄，读不出来的文件标红并写明原因。合计用的是 SUBTOTAL，筛选以后只算看得见的行。
   The workbook has two sheets: 发票 (one row per invoice, with totals; duplicates in yellow, unreadable files in red with the reason) and 明细 (one row per line item). Totals use SUBTOTAL, so they follow filters.

5. 检查发票抬头：加上 `--buyer`，购买方名称或税号不是你公司的发票会标出来（Excel 里标橙色）。名称和税号都要查，就写两次：
   Check who the invoices are made out to: with `--buyer`, invoices for another buyer name or tax ID are flagged (orange in Excel). Repeat it to check both:

   ```bash
   ofdkit 发票文件夹 --buyer 某某有限公司 --buyer 91310000XXXXXXXXXX
   ```

6. 按发票内容给文件改名，例如 `dzfp_2411…_20240528.ofd` 改成 `2024-05-28_某某公司_4449.00_2411….ofd`。不加 `--apply` 只是预览；同名的 PDF、XML 会一起改；改名记录可以用 `--undo` 改回去：
   Rename invoice files after their contents. Without `--apply` it only previews; PDF and XML copies with the same name are renamed too; `--undo` restores the old names from the log:

   ```bash
   ofdkit rename 发票文件夹            # 预览 / preview
   ofdkit rename 发票文件夹 --apply    # 改名 / rename
   ofdkit rename --undo 发票文件夹/改名记录_20261028_093000.csv
   ```

   名字的格式可以改，例如 `--pattern "{开票日期}_{购买方}_{商品}"`。可以用的字段：开票日期、发票号码、发票代码、发票种类、销售方、销售方税号、购买方、购买方税号、金额、税额、价税合计、商品、原文件名。
   The name format can be changed with `--pattern`; fields are listed by `ofdkit rename --help` (English names such as `{date}`, `{seller}` and `{total}` work too).

## 命令行 / Command line

```bash
ofdkit 文件.ofd                              # 看发票，不是发票就显示文字 / show an invoice, or the text
ofdkit 文件夹或压缩包.zip                     # 发票列表和合计 / list invoices with totals
ofdkit batch 文件夹 -o 发票汇总.xlsx          # 导出 Excel / export to Excel
ofdkit batch 文件夹 -o 发票汇总.csv           # 导出 CSV（给程序用）/ export CSV for programs
ofdkit 文件夹 --buyer 公司名或税号             # 检查发票抬头 / check the buyer
ofdkit rename 文件夹                         # 按内容改名（先预览）/ rename after contents (preview first)
ofdkit text 文件.ofd                         # 提取文字 / print text
ofdkit invoice 发票.ofd                      # 发票字段（JSON）/ invoice fields as JSON
ofdkit info 文件.ofd                         # 页数、作者等信息 / pages and metadata
ofdkit describe 文件.ofd -o 结构.json         # 打码的结构，用于报告问题 / masked structure for bug reports
```

`show`、`batch` 和 `rename` 加 `-r` 会连子文件夹一起找。`ofdkit 文件.ofd` 是 `ofdkit show 文件.ofd` 的简写。
Add `-r` to `show`, `batch` and `rename` to include subfolders. `ofdkit PATH` is short for `ofdkit show PATH`.

`ofdkit invoice` 的输出示例（数据是虚构的）/ Example output (fictional data):

```json
{
  "invoice_number": "00000000000000000001",
  "invoice_code": null,
  "issue_date": "2026-01-02",
  "check_code": null,
  "machine_number": null,
  "buyer": {"name": "测试单位甲", "tax_id": "TESTBUYER0001", "address_phone": null, "bank_account": null},
  "seller": {"name": "测试单位乙", "tax_id": "TESTSELLER0002", "address_phone": null, "bank_account": null},
  "amount_without_tax": "100.00",
  "tax_amount": "6.00",
  "total_amount": "106.00",
  "issuer": "测试人员",
  "payee": null,
  "reviewer": null,
  "note": null,
  "items": [
    {"name": "*测试*服务项目", "specification": null, "unit": null, "quantity": null,
     "unit_price": null, "amount": "100.00", "tax_rate": "6%", "tax_amount": "6.00"}
  ],
  "sources": ["custom_tags"],
  "warnings": []
}
```

金额是字符串，不会丢失精度。如果"合计金额 + 合计税额"不等于"价税合计"，`warnings` 里会提示。
Amounts are decimal strings, so no precision is lost. `warnings` notes totals that do not add up.

## 在 AI 工具里使用 / Use from AI tools

### MCP 服务器 / MCP server

让 Claude、Codex、Cursor 等 AI 工具直接读取 OFD 文件。需要先安装 [uv](https://docs.astral.sh/uv/)。所有工具都是只读的。
Lets Claude, Codex, Cursor and other AI tools read OFD files. Requires [uv](https://docs.astral.sh/uv/). All tools are read-only.

已在[官方 MCP Registry](https://registry.modelcontextprotocol.io/v0.1/servers?search=io.github.Edgar-311/ofdkit) 上架，名字是 `io.github.Edgar-311/ofdkit`；支持这个目录的工具可以直接搜索安装。
Listed in the [official MCP Registry](https://registry.modelcontextprotocol.io/v0.1/servers?search=io.github.Edgar-311/ofdkit) as `io.github.Edgar-311/ofdkit`; tools that read the registry can install it from there.

| 工具 / Tool | 作用 / What it does |
| --- | --- |
| `read_ofd_text` | 按阅读顺序提取文字，可选 Markdown 和页码范围 / text in reading order, optional Markdown and page range |
| `read_ofd_invoice` | 发票字段 / invoice fields |
| `ofd_info` | 页数、尺寸、元数据 / pages, sizes, metadata |
| `list_ofd_invoices` | 汇总一个文件夹里的发票，可以检查抬头 / summarise a folder of invoices, optionally checking the buyer |

Claude Code:

```bash
claude mcp add ofdkit -- uvx --from "ofdkit[mcp]" ofdkit mcp
```

Claude Desktop、Cursor 等使用 JSON 配置的工具 / tools with a JSON config:

```json
{
  "mcpServers": {
    "ofdkit": {
      "command": "uvx",
      "args": ["--from", "ofdkit[mcp]", "ofdkit", "mcp"]
    }
  }
}
```

Codex（`~/.codex/config.toml`）:

```toml
[mcp_servers.ofdkit]
command = "uvx"
args = ["--from", "ofdkit[mcp]", "ofdkit", "mcp"]
```

加上 `--root 文件夹` 可以只允许读取这个文件夹里的文件。
Add `--root FOLDER` to allow only files inside that folder.

### Agent Skill

[`skills/ofd-reader`](https://github.com/Edgar-311/ofdkit/tree/main/skills/ofd-reader) 告诉 AI 什么时候、怎么用 ofdkit 命令行，适用于支持 [Agent Skills](https://agentskills.io) 的工具。把这个文件夹复制到：
[`skills/ofd-reader`](https://github.com/Edgar-311/ofdkit/tree/main/skills/ofd-reader) tells an AI agent when and how to use the ofdkit command line. Copy the folder to:

- Claude Code: `~/.claude/skills/ofd-reader/`
- Codex: `~/.codex/skills/ofd-reader/`

### MarkItDown 插件 / MarkItDown plugin

[MarkItDown](https://github.com/microsoft/markitdown) 是把各种文件转成 Markdown 给 AI 读的工具。安装插件后它就能读 OFD：
[MarkItDown](https://github.com/microsoft/markitdown) converts files to Markdown for AI. With this plugin it reads OFD too:

```bash
pip install "ofdkit[markitdown]"
markitdown --use-plugins 发票.ofd
```

## Python

```python
import ofdkit

with ofdkit.open("发票.ofd") as doc:
    print(doc.text())
    invoice = doc.invoice()        # 不是发票时返回 None / None if not an invoice
    if invoice:
        print(invoice.invoice_number, invoice.total_amount)

# 文件夹、.zip 压缩包或多个文件 / folders, ZIP archives or several files
for result in ofdkit.read_invoices("发票文件夹", recursive=True, buyer=["某某有限公司"]):
    if result.invoice:
        print(result.file, result.invoice.total_amount, "重复" if result.duplicate else "", result.buyer_mismatch)
    else:
        print(result.file, result.error)
```

## 遇到读不出的文件 / Reporting a problem

请不要把真实发票发到网上。用这个命令导出文件结构，文字会全部打码，只保留结构和位置，然后附在 [GitHub issue](https://github.com/Edgar-311/ofdkit/issues/new/choose) 里：
Please do not post real invoices. Export the structure with all text masked and attach it to a [GitHub issue](https://github.com/Edgar-311/ofdkit/issues/new/choose):

```bash
ofdkit describe 文件.ofd -o 结构.json
```

## 注意 / Notes

- ofdkit 只读取文件里写了什么，不验证发票真伪。查验真伪请使用国家税务总局的发票查验平台。
  ofdkit reports what a file contains. It does not verify that an invoice is genuine.
- 文字如果是画成图形或图片的，就读不出来（需要 OCR，不在本项目范围内）。
  Text drawn as shapes or images cannot be extracted (that needs OCR, which is out of scope).
- 阅读顺序是根据位置推测的。两栏的正文会按栏读，表格按行读；版面特别复杂的页面（比如多栏加图片的杂志页）可能不完全准确。
  Reading order is inferred from positions. Prose columns are read column by column and tables row by row; very complex pages (magazine layouts with pictures) may not come out perfectly.

## 原则 / Principles

- 只读取 OFD，不生成、不修改发票。
  Reads OFD only. It never creates or modifies invoices.
- 本项目大部分代码由 AI（Claude）编写，维护者负责决定方向和批准发布。
  Most code is written with AI assistance (Claude). The maintainer sets the direction and approves releases.

## 许可证 / License

[Apache-2.0](https://github.com/Edgar-311/ofdkit/blob/main/LICENSE)
