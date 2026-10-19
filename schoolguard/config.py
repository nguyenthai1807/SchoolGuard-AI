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
