from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from jibu.config import Settings
from jibu.engine import Engine
from jibu.kb import KnowledgeBase, load_kb, load_kb_dir

ROOT = Path(__file__).resolve().parent.parent
AS_OF = date(2026, 6, 1)


@pytest.fixture(scope="session")
def kbs() -> dict[str, KnowledgeBase]:
    return load_kb_dir(ROOT / "kb")


@pytest.fixture(scope="session")
def sacco_kb() -> KnowledgeBase:
    return load_kb(ROOT / "kb" / "umoja-sacco.yaml")


@pytest.fixture(scope="session")
def engine(sacco_kb: KnowledgeBase) -> Engine:
    return Engine(sacco_kb, clock=lambda: AS_OF)


@pytest.fixture
def settings() -> Settings:
    return Settings(
        kb_dir=ROOT / "kb",
        default_kb="umoja-sacco",
        rate_limit=(1000, 60.0),
        admin_token="test-admin-token",
        hash_secret=b"x" * 32,
    )
