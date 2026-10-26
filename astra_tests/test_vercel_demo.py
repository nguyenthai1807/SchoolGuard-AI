"""The public academic preview must never contain the LH25 app or checkout."""

import json
from pathlib import Path
import re

import pytest

from scripts.build_vercel_demo import build, render_html


def test_vercel_demo_is_static_noncommercial(tmp_path):
    html, assets = render_html()
    lowered = html.lower()
    assert "demo học thuật" in lowered
    assert "không nhận đăng ký" in lowered
    assert "<form" not in lowered
    assert "<script" not in lowered
    assert "/api" not in lowered
    assert "payos" not in lowered
    assert "49.000" not in lowered
    assert "29.000" not in lowered
    assert "localhost" not in lowered

    output = tmp_path / "demo"
    build(output)
    assert {path.relative_to(output).as_posix() for path in output.rglob("*")
            if path.is_file()} == {"index.html", "vercel.json"} | {
                f"static/{name}" for name in assets}
    assert all((output / "static" / name).is_file() for name in assets)
    assert (output / "index.html").read_text(encoding="utf-8") == html
    config = json.loads((output / "vercel.json").read_text(encoding="utf-8"))
    headers = {entry["key"]: entry["value"]
               for entry in config["headers"][0]["headers"]}
    assert "form-action 'none'" in headers["Content-Security-Policy"]
    assert "script-src" not in headers["Content-Security-Policy"]
    assert headers["X-Robots-Tag"] == "noindex, nofollow"
    assert all(not ref.startswith("/api") for ref in re.findall(
        r'(?:href|src)="([^"]+)', html))


def test_vercel_demo_refuses_unreviewed_output(tmp_path):
    output = tmp_path / "demo"
    output.mkdir()
    (output / "private.txt").write_text("do not publish", encoding="utf-8")
    with pytest.raises(RuntimeError, match="Unexpected existing output"):
        build(output)
    assert (output / "private.txt").read_text(encoding="utf-8") == "do not publish"
