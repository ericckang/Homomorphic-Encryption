from __future__ import annotations

import os
from pathlib import Path


SHARED_DIR = Path(os.environ.get("HE_SHARED_DIR", "./he_shared")).resolve()
SERVER_URL = os.environ.get("HE_SERVER_URL", "http://localhost:8080/compute")

SHARED_DIR.mkdir(parents=True, exist_ok=True)
