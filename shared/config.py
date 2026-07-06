"""Config loader shared by all Python services.

Precedence: env vars (GOOGLE_CLOUD_PROJECT) > config.yaml > defaults.
Set CONFIG_PATH to the yaml file; defaults to ./config.yaml then /app/config.yaml.
"""
from __future__ import annotations

import functools
import os
from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class ModelsCfg(BaseModel):
    router: str = "gemini-2.5-flash"
    analytics: str = "gemini-2.5-pro"


class BigQueryCfg(BaseModel):
    dataset: str = "community_health"
    max_bytes_billed: int = 1 << 30
    row_limit: int = 200


class RagCfg(BaseModel):
    datastore_id: str = "health-knowledge"
    top_k: int = 8


class TopicsCfg(BaseModel):
    action_intents: str = "action-intents"
    alert_events: str = "alert-events"


class LimitsCfg(BaseModel):
    max_turn_tokens: int = 4096
    sql_retry_attempts: int = 2
    tool_timeout_s: int = 30


class AppConfig(BaseModel):
    project_id: str = ""
    region: str = "us-central1"
    models: ModelsCfg = Field(default_factory=ModelsCfg)
    bigquery: BigQueryCfg = Field(default_factory=BigQueryCfg)
    rag: RagCfg = Field(default_factory=RagCfg)
    topics: TopicsCfg = Field(default_factory=TopicsCfg)
    limits: LimitsCfg = Field(default_factory=LimitsCfg)


def _candidate_paths() -> list[Path]:
    paths = []
    if os.environ.get("CONFIG_PATH"):
        paths.append(Path(os.environ["CONFIG_PATH"]))
    paths.append(Path.cwd() / "config.yaml")
    paths.append(Path("/app/config.yaml"))
    # repo root relative to this file (shared/config.py -> repo root)
    paths.append(Path(__file__).resolve().parent.parent / "config.yaml")
    return paths


@functools.lru_cache(maxsize=1)
def load_config() -> AppConfig:
    data: dict = {}
    for path in _candidate_paths():
        if path.is_file():
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            break
    cfg = AppConfig.model_validate(data)
    env_project = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("PROJECT_ID")
    if env_project:
        cfg.project_id = env_project
    return cfg
