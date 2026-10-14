"""Regenerate the OpenAPI section of docs/API_CONVENTIONS.md from the app.

The document's §9 is the API's own schema; hand-editing it drifts. This script
imports the app, asks it for the schema it actually serves, and rewrites that
one fenced block. Run it after any route change:

    .venv/Scripts/python scripts/regen_openapi.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "API_CONVENTIONS.md"
HEADING = "## 9. OpenAPI 3.1 document"

sys.path.insert(0, str(ROOT))

import main  # noqa: E402  (must come after sys.path, and after the doc paths)

INTRO = (
    f"{HEADING}\n\n"
    "Generated from the running app — `scripts_regen_openapi.py` rewrites this\n"
    "block from `app.openapi()`, so it cannot drift from the code. No `servers`\n"
    "block is emitted: every documented path already carries the `/api/v1`\n"
    "prefix, and a `servers` entry on top of that would double it in Swagger's\n"
    "\"Try it out\".\n\n"
    "```yaml\n"
)


def main_doc() -> None:
    spec = main.app.openapi()
    body = yaml.safe_dump(spec, sort_keys=False, allow_unicode=True, width=88)
    text = DOC.read_text(encoding="utf-8")

    start = text.index(HEADING)
    end = text.index("```", text.index("```yaml", start) + 3) + 3
    if text[end:].strip():
        raise SystemExit(
            "Section 9 is no longer the last section of the document — "
            "refusing to truncate what follows it."
        )

    # Only the block is replaced, and the tail (whitespace) is dropped rather
    # than re-appended: re-appending grew the file by a blank line per run.
    #
    # `newline="\n"` matters: the default translates every `\n` to the
    # platform's line ending on write, which would rewrite all ~2,400 lines of
    # an LF file as CRLF and bury the real diff in whitespace noise.
    DOC.write_text(
        text[:start] + INTRO + body + "```\n", encoding="utf-8", newline="\n"
    )
    print("OpenAPI section regenerated: "
          f"{len(spec['paths'])} paths, "
          f"{sum(len(spec['paths'][p]) for p in spec['paths'])} operations")


if __name__ == "__main__":
    main_doc()
