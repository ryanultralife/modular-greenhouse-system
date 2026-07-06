#!/usr/bin/env python3
"""Regenerate docs/WALKTHROUGH.md from api/walkthrough_content.py.

Run after editing the walkthrough content so the shareable doc stays in sync:
    python3 scripts/gen_walkthrough_doc.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from api.walkthrough_content import render_markdown  # noqa: E402

OUT = ROOT / "docs" / "WALKTHROUGH.md"


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(render_markdown(), encoding="utf-8", newline="\n")
    print(f"Wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
