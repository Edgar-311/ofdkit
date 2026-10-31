# 第一次使用 ofdkit

本指南以 Windows 为例，目标是先读懂一份文件，再把一个文件夹汇总成 Excel。文件在本机处理，核心功能不需要账号或 AI 服务。

## 安装并确认能运行

从 [Python 官网](https://www.python.org/downloads/) 安装 Python 3.10 或更新版本。Windows 官方安装和命令说明见 [Python 文档](https://docs.python.org/3/using/windows.html)。安装后重新打开“终端”或 PowerShell。

先输入：

```powershell
py --version
```

能看到版本号后，逐行运行：

```powershell
py -m pip install --upgrade ofdkit
py -m ofdkit --version
```

看到 `ofdkit` 和版本号，就说明安装成功。这里始终通过同一个 Python 安装和运行，可以避开“装好了，却找不到 ofdkit 命令”的常见问题。

如果你的电脑能运行 `python`，但不能运行 `py`，把本指南每条命令开头的 `py` 换成 `python`。macOS / Linux 通常使用 `python3`；若系统要求使用虚拟环境，请按 [Python 虚拟环境说明](https://docs.python.org/3/library/venv.html) 创建后再安装。

## 先读一个普通样例

没有合适的测试文件时，可以下载公开的 [hello.ofd 普通文档样例](https://github.com/Edgar-311/ofd-samples/raw/refs/heads/main/samples/hello.ofd)。它是合成测试文档，不是真实发票。

输入 `py -m ofdkit `，再将文件拖进终端窗口，按回车。或者手动写完整路径，例如：

```powershell
py -m ofdkit "C:\报销\hello.ofd"
```

请把示例路径换成你实际保存文件的位置。程序会显示样例文字；如果读取的是带发票数据的 OFD，则显示号码、购销方和金额。

## 把文件夹或 ZIP 汇总到 Excel

将需要处理的文件放进一个文件夹。下面的路径也要替换成你自己的：

```powershell
py -m ofdkit "C:\报销\发票"
py -m ofdkit batch "C:\报销\发票" -o "发票汇总.xlsx"
```

第一条先查看结果，第二条导出。税务平台下载的 ZIP 可以直接作为输入：

```powershell
py -m ofdkit batch "C:\报销\下载.zip" -o "发票汇总.xlsx"
```

`发票汇总.xlsx` 会保存在终端当前所在文件夹。终端通常会在提示符里显示这个位置；也可以给 `-o` 写一个完整输出路径。输出文件夹需要已经存在。

输出文件应使用一个不同于原文件的名字，保留原 OFD 和 ZIP。已有同名汇总表会被替换；需要保留旧结果时，请换一个输出名字。

Excel 有“发票”和“明细”两张表。先看“提醒”一栏：重复、无法读取、抬头不符、金额缺失或不是数字都会有说明。合计只包含能识别为数字的金额，存在未计入的金额时会提示；请核对后再使用结果。

默认只查当前文件夹。要包含子文件夹，加上 `-r`：

```powershell
py -m ofdkit batch "C:\报销\发票" -r -o "发票汇总.xlsx"
```

## 常见问题

| 看到的情况 | 下一步 |
| --- | --- |
| `py` 或 `python` 找不到 | 确认 Python 已安装，重新打开终端；参考上面的官方 Windows 安装说明 |
| 找不到 `ofdkit` 命令 | 使用本指南的 `py -m ofdkit`；安装时也使用同一个 `py -m pip` |
| `No module named ofdkit` | 在同一终端运行 `py -m pip install --upgrade ofdkit` 后再试 |
| 找不到文件 | 核对完整路径，给含空格的路径加英文双引号；可直接拖入文件填写路径 |
| 没有权限保存 Excel | 关闭正在打开同名文件的 Excel，并选择可写的输出位置 |
| 没找到发票 | 确认文件是 OFD；文件只放在子文件夹时加 `-r`。PDF、图片和独立 XML 暂不支持 |
| 文件能打开，但没有文字 | 文字可能是图片或图形；ofdkit 当前没有图片文字识别功能 |

仍有问题时，记录版本号、运行的命令和现象。按 [项目的问题报告说明](../README.md#遇到读不出的文件--reporting-a-problem) 导出并检查打码结构，不要把真实发票附到公开 issue。

## 后续再尝试改名和 AI 接入

先完成上述查看和 Excel 导出，再按 [README](../README.md) 使用抬头检查、改名预览和 AI 接口。首次改名可以先在副本文件夹操作；不加 `--apply` 只会预览。
