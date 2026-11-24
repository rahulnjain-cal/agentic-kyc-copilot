"""Synthetic FSI data loaders and immutable snapshot helpers."""

from __future__ import annotations

import json
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"


def mint_snapshot_id(prefix: str) -> str:
    """Generates a deterministic-format immutable snapshot identifier."""
    short_token = uuid.uuid4().hex[:8].upper()
    return f"SNAP-{prefix.upper()}-{short_token}"


@lru_cache(maxsize=1)
def load_corporate_registries() -> dict[str, Any]:
    """Loads synthetic internal CRM and external corporate registry records."""
    path = DATA_DIR / "corporate_registries.json"
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def load_watchlists_and_media() -> dict[str, Any]:
    """Loads synthetic OFAC/UN/UK HMT/LSEG PEP watchlists and adverse media."""
    path = DATA_DIR / "watchlists_and_adverse_media.json"
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def load_transactions_90d() -> dict[str, Any]:
    """Loads synthetic 90-day corporate transaction profiles."""
    path = DATA_DIR / "transactions_90d.json"
    return json.loads(path.read_text(encoding="utf-8"))
