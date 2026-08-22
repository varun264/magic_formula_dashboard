import sys
from pathlib import Path

import pytest

DATA_PIPELINE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DATA_PIPELINE_DIR))

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _load(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def overview_html() -> str:
    return _load("overview_reliance.html")


@pytest.fixture(scope="session")
def profit_loss_html() -> str:
    return _load("profit_loss_reliance.html")


@pytest.fixture(scope="session")
def ratios_html() -> str:
    return _load("ratios_reliance.html")


@pytest.fixture(scope="session")
def quarterly_html() -> str:
    return _load("quarterly_reliance.html")
