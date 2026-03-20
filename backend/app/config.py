from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT_DIR / "data"


@dataclass(frozen=True)
class Settings:
    app_name: str
    database_url: str
    default_left_symbol: str
    default_right_symbol: str


def get_settings(database_url: str | None = None) -> Settings:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    resolved_database_url = database_url or os.getenv(
        "STYLE_ROTATION_DB_URL",
        f"sqlite+pysqlite:///{(DATA_DIR / 'style_rotation.db').as_posix()}",
    )
    return Settings(
        app_name="Style Rotation API",
        database_url=resolved_database_url,
        default_left_symbol="399376",
        default_right_symbol="399373",
    )

