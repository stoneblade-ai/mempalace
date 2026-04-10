import os
import json
import tempfile
from cortex.config import CortexConfig


def test_default_config():
    cfg = CortexConfig(config_dir=tempfile.mkdtemp())
    assert "palace" in cfg.palace_path
    assert cfg.collection_name == "cortex_drawers"


def test_config_from_file():
    tmpdir = tempfile.mkdtemp()
    with open(os.path.join(tmpdir, "config.json"), "w") as f:
        json.dump({"palace_path": "/custom/palace"}, f)
    cfg = CortexConfig(config_dir=tmpdir)
    assert cfg.palace_path == "/custom/palace"


def test_env_override():
    os.environ["CORTEX_PALACE_PATH"] = "/env/palace"
    cfg = CortexConfig(config_dir=tempfile.mkdtemp())
    assert cfg.palace_path == "/env/palace"
    del os.environ["CORTEX_PALACE_PATH"]


def test_init():
    tmpdir = tempfile.mkdtemp()
    cfg = CortexConfig(config_dir=tmpdir)
    cfg.init()
    assert os.path.exists(os.path.join(tmpdir, "config.json"))
