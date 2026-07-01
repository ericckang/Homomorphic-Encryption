from __future__ import annotations

import os
from pathlib import Path


class Settings:
    SHARED_DIR: Path = Path(os.environ.get("HE_SHARED_DIR", "./he_shared")).resolve()
    MAX_PAYLOAD_BYTES: int = int(os.environ.get("HE_MAX_PAYLOAD_BYTES", str(1_900_000_000)))
    HEX_PREVIEW_BYTES: int = int(os.environ.get("HE_HEX_PREVIEW_BYTES", "32"))
    HOST: str = os.environ.get("HE_HOST", "127.0.0.1")
    PORT: int = int(os.environ.get("HE_PORT", "8080"))


settings = Settings()
settings.SHARED_DIR.mkdir(parents=True, exist_ok=True)
