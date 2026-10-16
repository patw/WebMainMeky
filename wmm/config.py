"""Configuration: .env loading and tunables. Stdlib only."""
from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_env(path: Path | None = None) -> dict:
    """Minimal KEY=VALUE .env loader (no python-dotenv dependency)."""
    path = path or PROJECT_ROOT / ".env"
    out = {}
    if path.exists():
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            out[key.strip()] = val.strip().strip('"').strip("'")
    return out


_ENV = load_env()


def _get(key: str, default: str) -> str:
    return os.environ.get(key) or _ENV.get(key) or default


def _num(key: str, default, cast=float):
    raw = os.environ.get(key) or _ENV.get(key)
    return cast(raw) if raw not in (None, "") else default


# --- LLM (authoring only) ---
OPENAI_BASE_URL = _get("OPENAI_BASE_URL", "http://127.0.0.1:8086/v1")
OPENAI_API_KEY = _get("OPENAI_API_KEY", "doesntmatter")
OPENAI_MODEL = _get("OPENAI_MODEL", "local")
OPENAI_TIMEOUT = _num("OPENAI_TIMEOUT", 120.0, float)

# --- storage ---
DATA_DIR = PROJECT_ROOT / _get("WMM_DATA_DIR", "store")

# --- rule policy ---
MIN_SUPPORT = int(_num("WMM_MIN_SUPPORT", 3, int))
MIN_CONFIDENCE = float(_num("WMM_MIN_CONFIDENCE", 0.55, float))

# --- validation gate ---
MIN_CHARS = int(_num("WMM_MIN_CHARS", 220, int))
MIN_SENTENCES = int(_num("WMM_MIN_SENTENCES", 3, int))
MAX_LINK_DENSITY = float(_num("WMM_MAX_LINK_DENSITY", 0.55, float))

# --- generic-tier scoring weights (tuned by scripts/ablate_generic.py) ---
W_PROSE = float(_num("WMM_W_PROSE", 0.55, float))
W_DENSITY = float(_num("WMM_W_DENSITY", 0.45, float))
RUN_BONUS = float(_num("WMM_RUN_BONUS", 0.25, float))
BOILER_PENALTY = float(_num("WMM_BOILER_PENALTY", 0.6, float))
MIN_PROSE = int(_num("WMM_MIN_PROSE", 25, int))

# --- trimming switches (ablated by scripts/diagnose.py) ---
TRIM = int(_num("WMM_TRIM", 1, int)) == 1
TRIM_STOP = int(_num("WMM_TRIM_STOP", 1, int)) == 1
TRIM_LINKLIST = int(_num("WMM_TRIM_LINKLIST", 1, int)) == 1
TRIM_LOWVALUE = int(_num("WMM_TRIM_LOWVALUE", 1, int)) == 1
MIN_CHARS_BEFORE_STOP = int(_num("WMM_STOP_AFTER_CHARS", 300, int))

# --- golden regression gate ---
GOLDEN_GATE = int(_num("WMM_GOLDEN_GATE", 1, int)) == 1
GOLDEN_MIN = float(_num("WMM_GOLDEN_MIN", 0.55, float))
GOLDEN_LIMIT = int(_num("WMM_GOLDEN_LIMIT", 60, int))
