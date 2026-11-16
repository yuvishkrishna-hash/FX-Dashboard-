"""Inline the dashboard template, CSS, and script into one HTML file."""

from __future__ import annotations

import json
from pathlib import Path

STATIC = Path(__file__).resolve().parent / "static"


def render_page(data: dict) -> str:
    html = (STATIC / "dashboard.html").read_text(encoding="utf-8")
    css = (STATIC / "dashboard.css").read_text(encoding="utf-8")
    js = (STATIC / "dashboard.js").read_text(encoding="utf-8")
    payload = json.dumps(data, separators=(",", ":"), ensure_ascii=True).replace("<", "\\u003c")
    page = html.replace("__CSS__", css).replace("__JS__", js).replace("__DATA__", payload)
    if "__CSS__" in page or "__JS__" in page or "__DATA__" in page:
        raise RuntimeError("A dashboard placeholder was left in the rendered page.")
    return page
