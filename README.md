# ofdkit

轻量的 Python 工具，用来读取 OFD 文件，提取里面的文字和发票字段，并能接入 AI 工具。OFD 是中国的国家标准版式文档格式（GB/T 33190），常见于电子发票和公文。

A lightweight Python toolkit for reading OFD documents (GB/T 33190, the Chinese fixed-layout format used for e-invoices and official documents): extract text and invoice fields, and use them from AI tools.

> 状态：开发中，0.1.0 还没有发布，可以先从 GitHub 安装试用。
> Status: under development. 0.1.0 is not released yet; install from GitHub to try it.

## 能做什么 / What it does

- 按阅读顺序提取文字，包括模板和复合对象里的文字。
  Text in reading order, including text in templates and composite objects.
- 读取电子发票字段（数电票和增值税电子发票），输出 JSON：发票号码、开票日期、购买方、销售方、金额、税额、价税合计、明细。
  Invoice fields from e-invoices as JSON: number, date, buyer, seller, amounts, tax, total, line items.
- 把一个文件夹里的发票汇总成 CSV，Excel 可以直接打开，并提示重复的发票号码。
  A folder of invoices summarised as CSV (opens in Excel), with duplicate invoice numbers flagged.
- 只用 Python 标准库，没有任何第三方依赖；能读很多不规范的文件（路径写法不对、编码不对、XML 前缀错误等）。
  Standard library only, no dependencies; reads many non-conforming files (bad paths, encodings, XML prefixes).

## 安装 / Install

需要 Python 3.10 或更新版本。Requires Python 3.10+.

```bash
pip install "git+https://github.com/Edgar-311/ofdkit"
```

## 命令行 / Command line

```bash
ofdkit text 文件.ofd                         # 提取文字 / print text
ofdkit invoice 发票.ofd                      # 发票字段（JSON）/ invoice fields as JSON
ofdkit batch 发票文件夹/ -o 发票汇总.csv      # 批量汇总 / summarise a folder as CSV
ofdkit info 文件.ofd                         # 页数、作者等信息 / pages and metadata
```

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

| 工具 / Tool | 作用 / What it does |
| --- | --- |
| `read_ofd_text` | 按阅读顺序提取文字，可选 Markdown 和页码范围 / text in reading order, optional Markdown and page range |
| `read_ofd_invoice` | 发票字段 / invoice fields |
| `ofd_info` | 页数、尺寸、元数据 / pages, sizes, metadata |
| `list_ofd_invoices` | 汇总一个文件夹里的发票 / summarise a folder of invoices |

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

加上 `--root 文件夹` 可以只允许读取这个文件夹里的文件。在 0.1.0 发布到 PyPI 之前，把 `ofdkit[mcp]` 换成 `ofdkit[mcp] @ git+https://github.com/Edgar-311/ofdkit`。
Add `--root FOLDER` to allow only files inside that folder. Until 0.1.0 is on PyPI, replace `ofdkit[mcp]` with `ofdkit[mcp] @ git+https://github.com/Edgar-311/ofdkit`.

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
```

## 注意 / Notes

- ofdkit 只读取文件里写了什么，不验证发票真伪。查验真伪请使用国家税务总局的发票查验平台。
  ofdkit reports what a file contains. It does not verify that an invoice is genuine.
- 文字如果是画成图形或图片的，就读不出来（需要 OCR，不在本项目范围内）。
  Text drawn as shapes or images cannot be extracted (that needs OCR, which is out of scope).
- 多栏排版的页面，目前两栏的文字会出现在同一行，用三个空格隔开。
  On multi-column pages, both columns currently share each line, separated by three spaces.

## 原则 / Principles

- 只读取 OFD，不生成、不修改发票。
  Reads OFD only. It never creates or modifies invoices.
- 本项目大部分代码由 AI（Claude）编写，维护者负责决定方向和批准发布。
  Most code is written with AI assistance (Claude). The maintainer sets the direction and approves releases.

## 许可证 / License

[Apache-2.0](LICENSE)
