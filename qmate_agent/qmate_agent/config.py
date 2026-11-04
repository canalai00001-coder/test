import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
OUTPUT_DIR = ROOT / "output"
STATE_DIR = ROOT / "state"


def load(name: str) -> dict:
    """config/<name> を読む。同じ場所に <名前>.local.json（例: settings.local.json）があれば、その値で上書きする。

    ウェブアプリの URL のような各自の値は .local.json に書いておけば、ZIP を取り直して
    settings.json を上書きしても消えない（.local.json は ZIP に入っていない）。
    """
    with open(CONFIG_DIR / name, encoding="utf-8") as f:
        data = json.load(f)
    local = CONFIG_DIR / f"{Path(name).stem}.local.json"
    if local.exists():
        with open(local, encoding="utf-8") as f:
            data = _merge(data, json.load(f))
    return data


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out
