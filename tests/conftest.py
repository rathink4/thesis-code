import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sbess.config import load_config  # noqa: E402


@pytest.fixture
def cfg():
    return load_config("synthetic_test")
