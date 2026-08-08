"""Repo-anchored paths. medeval lives at packages/eval/src/medeval — repo root is 4 up."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
DEMO_DIR = REPO_ROOT / "demo"
DATASETS_DIR = REPO_ROOT / "packages" / "eval" / "datasets"
REPORTS_DIR = REPO_ROOT / "eval-reports"
