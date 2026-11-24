"""Shared helpers: findings, file I/O, hashing, config and .env loading (SPEC §11)."""
from __future__ import annotations

import copy
import csv
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore

HARNESS_VERSION = "1.0.0"

PRIMARY = ["Atelectasis", "Cardiomegaly", "Consolidation", "Edema", "Pleural Effusion"]
SECONDARY = ["No Finding"]
FINDINGS = PRIMARY + SECONDARY

MANIFEST_COLUMNS = ["case_id", "images", "views", "sha256"]
SEALED_DIRNAME = "_sealed"

DEFAULT_CONFIG: dict = {
    "model": {"name": "claude-opus-5-5", "max_tokens": 16000, "extra": {}},
    "run": {
        "prompt": "prompts/v1.txt",
        "concurrency": 4,
        "parse_retries": 1,
        "api_max_retries": 5,
        "batch_max_mb": 100,
        "poll_seconds": 60,
    },
    "score": {
        "threshold": 50,
        "bootstrap": 1000,
        "seed": 42,
        "max_parse_failure_rate": 0.02,
        "misses_per_finding": 10,
    },
    "cost": {"input_per_mtok": 4.0, "output_per_mtok": 20.0, "batch_discount": 0.5},
    "baseline": {},
}


class HarnessError(Exception):
    """A problem that should stop the current command with a clear message."""


def die(message: str, code: int = 2) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(code)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_json(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def read_json(path: str | Path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json(path: str | Path, obj) -> None:
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def read_csv(path: str | Path) -> tuple[list[str], list[dict]]:
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        return list(reader.fieldnames or []), rows


def write_csv(path: str | Path, rows: list[dict], fieldnames: list[str]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="raise")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def load_config(path: str | Path | None) -> dict:
    """Load config.toml merged over DEFAULT_CONFIG. A missing file means defaults."""
    if path is None or not Path(path).exists():
        return copy.deepcopy(DEFAULT_CONFIG)
    with open(path, "rb") as f:
        user = tomllib.load(f)
    return _deep_merge(DEFAULT_CONFIG, user)


def load_dotenv(path: str | Path = ".env") -> None:
    """Minimal .env loader (KEY=VALUE lines). Never overrides variables already set."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def public_golden_paths(golden_dir: str | Path) -> dict:
    """The only golden-set files the blinded runner may open."""
    g = Path(golden_dir)
    return {"root": g, "images": g / "images", "manifest": g / "manifest.csv", "lock": g / "golden_lock.json"}


def sealed_golden_paths(golden_dir: str | Path) -> dict:
    """Reference-standard files. Only prepare_golden, score and compare touch these."""
    g = Path(golden_dir)
    sealed = g / SEALED_DIRNAME
    return {
        "dir": sealed,
        "truth": sealed / "labels.csv",
        "source_map": sealed / "source_map.csv",
        "summary": sealed / "summary.json",
    }


def lock_id_for(lock: dict) -> str:
    """lock_id = SHA-256 of the lock contents excluding creation time and the id itself (SPEC §7)."""
    body = {k: v for k, v in lock.items() if k not in ("created_utc", "lock_id")}
    return sha256_bytes(canonical_json(body).encode("utf-8"))


def read_jsonl(path: str | Path) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    out = []
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out
