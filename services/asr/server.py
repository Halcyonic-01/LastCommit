"""ASR Server wrapper pointing to unified VarshaDrishti Voice Server."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "services"))

from services.voice.server import main

if __name__ == "__main__":
    sys.exit(main())
