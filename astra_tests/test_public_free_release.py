from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def test_public_store_includes_every_local_asset_and_no_weapon_offer():
    public = ROOT / "hosting" / "public"
    html = (public / "index.html").read_text(encoding="utf-8")
    assert "child-home-observation.png" in html
    assert "elderly-home-fall-feature.png" in html
    assert "store-group-consented.webp" in html
    assert "hung khí" not in html.lower()
    assert "weapon" not in html.lower()
    for asset in set(re.findall(r'["\'](/static/[\w.-]+)', html)):
        assert (public / asset.lstrip("/")).is_file(), asset


def test_browser_free_has_only_yolo8_9_10_not_paid_yolo26():
    app = ROOT / "hosting" / "firebase-spark" / "app"
    for name in ("yolov8n", "yolov9t", "yolov10n"):
        assert (app / "models" / f"{name}.onnx").read_bytes() == (ROOT / "models" / f"{name}.onnx").read_bytes()
    assert not (app / "models" / "yolo26n.onnx").exists()
    assert "await import('/browser.js')" in (app / "analyze.js").read_text(encoding="utf-8")
    assert "No payment credential" in (app / "portal-free.js").read_text(encoding="utf-8")


def test_public_app_uses_original_lh25_shell_without_claiming_full_backend():
    app = ROOT / "hosting" / "firebase-spark" / "app"
    for page in ("index.html", "analyze.html"):
        html = (app / page).read_text(encoding="utf-8")
        assert "/static/brand-lh25-original.jpg" in html
        assert "/static/lh25-green.css" in html
        assert "Lock Home 24 + 1 / 7" in html
        assert "LH25 STORE" in html
    for name in ("style.css", "lh25.css", "lh25-green.css", "brand-lh25-original.jpg"):
        assert (app / "static" / name).read_bytes() == (ROOT / "schoolguard" / "static" / name).read_bytes()
    index = (app / "index.html").read_text(encoding="utf-8")
    assert "Chưa mở thanh toán trên web" in index
    assert "video và khung hình chỉ được xử lý" in index.lower()


def test_new_weapon_jobs_are_rejected(client, request_data):
    job = client.post("/api/jobs", json={**request_data, "detect_weapons": True})
    live = client.post("/api/live/start", json={"source_id": "live", "detect_weapons": True})
    assert job.status_code == live.status_code == 422
    assert client.get("/api/system").json()["weapon_available"] is False
    assert "weapon" not in client.get("/api/admin/demo-videos").json()["capabilities"]
