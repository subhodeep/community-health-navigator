"""Shared runtime dependencies for the API service (Firestore client, agent URL)."""
from __future__ import annotations

import functools
import os

from google.cloud import firestore

from shared.config import load_config


@functools.lru_cache(maxsize=1)
def get_db() -> firestore.AsyncClient:
    """Lazily-constructed, process-wide async Firestore client."""
    cfg = load_config()
    return firestore.AsyncClient(project=cfg.project_id or None)


def agent_url() -> str:
    """Base URL of the internal agent service. AGENT_URL env var is required."""
    url = os.environ.get("AGENT_URL", "").rstrip("/")
    if not url:
        raise RuntimeError("AGENT_URL environment variable is required")
    return url
