"""Paths, model settings, and the API key check.

Models are constants that can be overridden with the MODEL and
ESCALATION_MODEL environment variables (for example in .env).
"""

import os
import sys
from pathlib import Path

import anthropic
from dotenv import load_dotenv

# parents: [0] invoice_batch/, [1] src/, [2] the project root
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
INVOICES_DIR = DATA_DIR / "invoices"
GROUND_TRUTH = DATA_DIR / "ground_truth.json"
RUNS_DIR = PROJECT_ROOT / "runs"

load_dotenv(PROJECT_ROOT / ".env")

# Verified against platform.claude.com models overview (Nov 2026).
MODEL = os.getenv("MODEL", "claude-haiku-5-5")
ESCALATION_MODEL = os.getenv("ESCALATION_MODEL", "claude-sonnet-5-5")

_PLACEHOLDER_KEY = "your-anthropic-api-key-here"


def require_api_key() -> None:
    """Exit with a helpful message if the key is missing. Never prints it."""
    key = os.getenv("ANTHROPIC_API_KEY", "")
    if not key or key == _PLACEHOLDER_KEY:
        sys.exit(
            "ANTHROPIC_API_KEY is not set.\n  cp .env.example .env   then put your key in .env"
        )


def make_client():
    require_api_key()
    return anthropic.Anthropic()


def pdf_path_for(custom_id: str) -> Path:
    return INVOICES_DIR / f"{custom_id}.pdf"
