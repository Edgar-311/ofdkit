# ofdkit

轻量的 Python 工具，用来读取 OFD 文件，提取里面的文字和发票字段，并能接入 AI 工具。OFD 是中国的国家标准版式文档格式（GB/T 33190），常见于电子发票和公文。

A lightweight Python toolkit for reading OFD documents (GB/T 33190, the Chinese fixed-layout format used for e-invoices and official documents): extract text and invoice fields, and use them from AI tools.

> 状态：开发中，还没有可用的版本。
> Status: under development, no release yet.

## 原则 / Principles

- 只读取 OFD，不生成、不修改发票。
  Reads OFD only. It never creates or modifies invoices.
- 本项目大部分代码由 AI（Claude）编写，维护者负责决定方向和批准发布。
  Most code is written with AI assistance (Claude). The maintainer sets the direction and approves releases.

## 许可证 / License

[Apache-2.0](LICENSE)
