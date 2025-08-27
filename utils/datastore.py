import json
from pathlib import Path
from typing import Any
from loguru import logger

DATA_DIR = Path("data")
DATA_DIR.mkdir(parents=True, exist_ok=True)

def load_json(path: Path, default: Any) -> Any:
    try:
        if not path.exists():
            return default
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"[datastore] load_json failed for {path}: {e}")
        return default

def save_json(path: Path, obj: Any) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        tmp.replace(path)
    except Exception as e:
        logger.warning(f"[datastore] save_json failed for {path}: {e}")
