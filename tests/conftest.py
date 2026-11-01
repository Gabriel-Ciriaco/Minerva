import json
import shutil
from pathlib import Path

import pytest

from minerva import index

CORPUS = Path(__file__).resolve().parent / "corpus"


@pytest.fixture
def workspace(tmp_path):
    """Cópia do corpus sintético (tests/generate_corpus.py), já indexada."""
    ws = tmp_path / "ws"
    shutil.copytree(CORPUS, ws)
    index.ingest(ws)
    return ws


@pytest.fixture
def con(workspace):
    c = index.connect_ro(workspace)
    yield c
    c.close()


def loads(payload):
    return json.loads(payload)
