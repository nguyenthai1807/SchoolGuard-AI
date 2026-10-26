import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_local_env():
    """Load local secrets without introducing a runtime dependency."""
    path = ROOT / ".env"
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


load_local_env()


@dataclass
class Settings:
    data_root: Path = Path(
        os.environ.get("SCHOOLGUARD_DATA", Path.home() / "Downloads/splits/splits/shanghaitech")
    )
    runtime: Path = Path(os.environ.get("LH25_RUNTIME_DIR", ROOT / "runtime"))
    models: Path = ROOT / "models"
    start_worker: bool = True
    max_upload_bytes: int = 1024 * 1024 * 1024
    public_base_url: str = os.environ.get("LH25_PUBLIC_BASE_URL", "")
    email_verification_required: bool = os.environ.get("LH25_REQUIRE_VERIFIED_EMAIL", "false").lower() == "true"
    payment_enabled: bool = os.environ.get("LH25_PAYOS_ENABLED", "false").lower() == "true"
    manual_bank_name: str = os.environ.get("LH25_MANUAL_BANK_NAME", "").strip()
    manual_bank_account: str = os.environ.get("LH25_MANUAL_BANK_ACCOUNT", "").strip()
    manual_bank_recipient: str = os.environ.get("LH25_MANUAL_BANK_RECIPIENT", "").strip()
    google_client_id: str = os.environ.get("LH25_GOOGLE_CLIENT_ID", "")
    google_only: bool = os.environ.get("LH25_GOOGLE_ONLY", "false").lower() == "true"
    google_admin_subjects: tuple[str, ...] = tuple(
        s.strip() for s in os.environ.get("LH25_GOOGLE_ADMIN_SUBS", "").split(",") if s.strip()
    )
