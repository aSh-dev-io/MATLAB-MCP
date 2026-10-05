"""Shared fixtures.

Tests run against the real Stage 1 artefacts, because the point of Phase 2A is
to validate those specific files. Session-scoped loading keeps the suite fast.
"""

from __future__ import annotations

import pytest

from ganstage2.config import Stage2Config
from ganstage2.dataset import build_dataset
from ganstage2.ingestion import load_stage1


@pytest.fixture(scope="session")
def cfg() -> Stage2Config:
    return Stage2Config()


@pytest.fixture(scope="session")
def bundle(cfg: Stage2Config):
    return load_stage1(cfg)


@pytest.fixture(scope="session")
def artifacts(bundle, cfg: Stage2Config):
    return build_dataset(bundle, cfg)
