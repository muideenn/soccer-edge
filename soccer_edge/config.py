import hashlib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def load_config(path=None):
    path = Path(path) if path else ROOT / "config.yaml"
    raw = path.read_bytes()
    cfg = yaml.safe_load(raw)
    cfg["_hash"] = hashlib.sha256(raw).hexdigest()[:12]
    cfg["_root"] = str(ROOT)
    return cfg


def p(cfg, key):
    """Resolve a configured path relative to the project root."""
    return Path(cfg["_root"]) / cfg["paths"][key]
