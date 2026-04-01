import json
from pathlib import Path

import pytest
import yaml


SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "schemas"
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"


@pytest.fixture
def schemas_dir():
    return SCHEMAS_DIR


@pytest.fixture
def templates_dir():
    return TEMPLATES_DIR


@pytest.fixture
def load_schema(schemas_dir):
    def _load(name: str) -> dict:
        path = schemas_dir / name
        if path.suffix in (".yaml", ".yml"):
            return yaml.safe_load(path.read_text())
        return json.loads(path.read_text())
    return _load


@pytest.fixture
def load_template(templates_dir):
    def _load(name: str):
        path = templates_dir / name
        if path.suffix in (".yaml", ".yml"):
            return yaml.safe_load(path.read_text())
        if path.suffix == ".json":
            return json.loads(path.read_text())
        return path.read_text()
    return _load
