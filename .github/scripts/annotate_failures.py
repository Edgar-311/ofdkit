"""Turn unittest failures in a saved test log into GitHub annotations.

Annotations show on the run's summary page and through the API, so a failure can be
read without downloading the full log.
"""

import sys
from pathlib import Path

SEPARATOR = "=" * 70


def escape(text: str) -> str:
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def escape_property(text: str) -> str:
    return escape(text).replace(":", "%3A").replace(",", "%2C")


def main(path: str) -> None:
    log = Path(path).read_text(encoding="utf-8", errors="replace")
    blocks = log.split(SEPARATOR)[1:]
    for block in blocks[:10]:  # GitHub keeps at most 10 error annotations per step
        lines = block.strip("\n").splitlines()
        if not lines or not lines[0].startswith(("FAIL:", "ERROR:")):
            continue
        body = []
        for line in lines[1:]:
            if line.startswith("Ran "):
                break
            if line.strip("-"):
                body.append(line)
        print(f"::error title={escape_property(lines[0])}::{escape(chr(10).join(body)[-3000:])}")
    if not blocks:
        print(f"::error title=Tests failed::{escape(log[-3000:])}")


if __name__ == "__main__":
    main(sys.argv[1])
