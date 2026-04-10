import os
import json
import tempfile
from cortex.config import CortexConfig


def test_default_config():
    cfg = CortexConfig(config_dir=tempfile.mkdtemp())
    assert "cortex" in cfg.cortex_path
    assert cfg.collection_name == "cortex_drawers"


def test_config_from_file():
    tmpdir = tempfile.mkdtemp()
    with open(os.path.join(tmpdir, "config.json"), "w") as f:
        json.dump({"cortex_path": "/custom/cortex"}, f)
    cfg = CortexConfig(config_dir=tmpdir)
    assert cfg.cortex_path == "/custom/cortex"


def test_env_override():
    os.environ["CORTEX_PATH"] = "/env/cortex"
    cfg = CortexConfig(config_dir=tempfile.mkdtemp())
    assert cfg.cortex_path == "/env/cortex"
    del os.environ["CORTEX_PATH"]


def test_init():
    tmpdir = tempfile.mkdtemp()
    cfg = CortexConfig(config_dir=tmpdir)
    cfg.init()
    assert os.path.exists(os.path.join(tmpdir, "config.json"))
