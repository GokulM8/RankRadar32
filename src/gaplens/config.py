"""Configuration loading for GapLens."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
VALID_ROLES = {"client", "competitor"}


def load_config(path: str | Path = "config.yaml") -> dict[str, Any]:
    """Load and validate the YAML config; resolve all `paths` entries to absolute paths.

    Also loads environment variables from `.env` in the repository root, if present.
    """
    path = Path(path)
    if not path.is_absolute() and not path.exists():
        path = REPO_ROOT / path
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    load_dotenv(REPO_ROOT / ".env")
    _validate(cfg)
    cfg["paths"] = {k: REPO_ROOT / v for k, v in cfg["paths"].items()}
    return cfg


def _validate(cfg: dict[str, Any]) -> None:
    """Fail early on obviously broken configs."""
    for key in ("paths", "crawl", "sites", "sectionize", "embedding", "umap", "hdbscan", "gaps", "scoring", "llm"):
        if key not in cfg:
            raise ValueError(f"config.yaml is missing the '{key}' section")

    roles = [s.get("role") for s in cfg["sites"]]
    if any(r not in VALID_ROLES for r in roles):
        raise ValueError(f"site roles must be one of {VALID_ROLES}, got {roles}")
    if roles.count("client") != 1:
        raise ValueError("exactly one site must have role 'client'")

    weights = cfg["scoring"]["weights"]
    if abs(sum(weights.values()) - 1.0) > 1e-6:
        raise ValueError(f"scoring weights must sum to 1.0, got {sum(weights.values()):.3f}")

    sec = cfg["sectionize"]
    if sec["min_words"] >= sec["max_words"]:
        raise ValueError("sectionize.min_words must be smaller than max_words")


def get_api_key(cfg: dict[str, Any]) -> str | None:
    """Return the LLM API key from the environment, or None if it is not set."""
    key = os.environ.get(cfg["llm"].get("api_key_env", "NVIDIA_API_KEY"), "").strip()
    return key or None


def client_site(cfg: dict[str, Any]) -> str:
    """Return the name of the client site."""
    return next(s["name"] for s in cfg["sites"] if s["role"] == "client")
