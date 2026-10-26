#!/usr/bin/env python3
"""repo-world builder: world.json (+ optional lore.json) -> single self-contained HTML game."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parent.parent / "assets" / "template.html"


def js_literal(data) -> str:
    # Safe inside <script>: no "</script>" breakout, no U+2028/2029 line terminators.
    s = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return s.replace("</", "<\\/").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def validate_lore(lore: dict, world: dict) -> list[str]:
    paths = {f["path"] for d in world["districts"] for f in d["files"]}
    names = {d["name"] for d in world["districts"]}
    warn = []
    for p in (lore.get("npcs") or {}):
        if p not in paths:
            warn.append(f"npcs: unknown file '{p}'")
    for n in (lore.get("districts") or {}):
        if n not in names:
            warn.append(f"districts: unknown district '{n}'")
    for q in lore.get("quests") or []:
        t = q.get("target", "")
        if not t.startswith(("kind:", "role:", "hero:", "district:")) and t not in paths:
            warn.append(f"quest '{q.get('title')}': unknown target '{t}'")
    return warn


def main() -> int:
    ap = argparse.ArgumentParser(description="Build the repo-world HTML game")
    ap.add_argument("world", nargs="?", default="world.json")
    ap.add_argument("-l", "--lore", default=None, help="optional lore.json written by Claude")
    ap.add_argument("-o", "--out", default="repo-world.html")
    a = ap.parse_args()
    for s in (sys.stdout, sys.stderr):  # Windows consoles default to cp1252
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8", errors="replace")

    world = json.loads(Path(a.world).read_text(encoding="utf-8"))
    lore = None
    if a.lore and Path(a.lore).exists():
        lore = json.loads(Path(a.lore).read_text(encoding="utf-8"))
        for w in validate_lore(lore, world):
            print(f"⚠ {w}", file=sys.stderr)

    html = TEMPLATE.read_text(encoding="utf-8")
    for token, value in (('"__WORLD_JSON__"', world), ('"__LORE_JSON__"', lore)):
        if token not in html:
            print(f"template missing {token}", file=sys.stderr)
            return 1
        html = html.replace(token, js_literal(value), 1)

    Path(a.out).write_text(html, encoding="utf-8")
    kb = len(html.encode()) / 1024
    print(f"✓ {a.out} ({kb:.0f} KB){' with lore' if lore else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
