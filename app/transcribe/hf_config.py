"""Hugging Face token config -- mirrors app.integrations.sheets_client's
config-loading pattern: missing/invalid config must never crash startup, just
disable the feature with a clear reason.
"""

import logging
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

TRANSCRIBE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = TRANSCRIBE_DIR / "hf_config.yaml"


def load_hf_token() -> str | None:
    if not CONFIG_PATH.exists():
        return None
    try:
        raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
        token = (raw.get("hf_token") or "").strip()
        return token or None
    except Exception:
        logger.exception("hf_config.yaml present but invalid")
        return None
