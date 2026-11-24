"""Blinded runner: sends each golden case to the model, one study per call (SPEC §5, §6, §7, §11.2).

This module only opens the public golden files (manifest, lock, images). It never opens the reference
standard; the self-test fails if this file mentions the sealed folder.

Examples:
    python -m harness.run_eval --show-request
    python -m harness.run_eval --limit 5
    python -m harness.run_eval --mode batch
    python -m harness.run_eval --mock --limit 10          # no API calls
"""
from __future__ import annotations

import argparse
import base64
import csv
import json
import os
import platform
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .common import (
    FINDINGS,
    HARNESS_VERSION,
    MANIFEST_COLUMNS,
    canonical_json,
    die,
    load_config,
    load_dotenv,
    public_golden_paths,
    read_json,
    read_jsonl,
    sha256_bytes,
    sha256_file,
    utc_now,
    write_csv,
    write_json,
)


class ParseError(Exception):
    pass


# ---------------------------------------------------------------- golden set (public part only)

def load_public_golden(golden_dir: Path) -> tuple[dict, list[dict]]:
    paths = public_golden_paths(golden_dir)
    if not paths["lock"].exists() or not paths["manifest"].exists():
        die(f"{golden_dir} is not a golden set (missing golden_lock.json or manifest.csv)")
    lock = read_json(paths["lock"])
    with open(paths["manifest"], newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if list(reader.fieldnames or []) != MANIFEST_COLUMNS:
            die(f"manifest columns must be exactly {MANIFEST_COLUMNS}, found {reader.fieldnames}")
        rows = list(reader)
    if sha256_file(paths["manifest"]) != lock.get("manifest_sha256"):
        die("manifest.csv does not match golden_lock.json: the golden set was changed")
    cases, all_hashes = [], []
    for row in rows:
        images, views, hashes = row["images"].split(";"), row["views"].split(";"), row["sha256"].split(";")
        if not (len(images) == len(views) == len(hashes)):
            die(f"manifest row {row['case_id']} is malformed")
        for name, expected in zip(images, hashes):
            actual = sha256_file(paths["images"] / name)
            if actual != expected:
                die(f"golden image hash mismatch for {name}: the golden set was changed")
            all_hashes.append(actual)
        cases.append({"case_id": row["case_id"], "images": images, "views": views})
    if sha256_bytes(";".join(all_hashes).encode("utf-8")) != lock.get("images_sha256"):
        die("image hashes do not match golden_lock.json: the golden set was changed")
    return lock, cases


# ---------------------------------------------------------------- request and parsing

def build_request(case: dict, images_dir: Path, prompt_text: str, cfg: dict) -> dict:
    content = []
    for i, (name, view) in enumerate(zip(case["images"], case["views"]), start=1):
        data = base64.b64encode((images_dir / name).read_bytes()).decode("ascii")
        content.append({"type": "text", "text": f"Image {i} ({view}):"})
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": data}})
    content.append({"type": "text", "text": prompt_text})
    params = {
        "model": cfg["model"]["name"],
        "max_tokens": int(cfg["model"]["max_tokens"]),
        "messages": [{"role": "user", "content": content}],
    }
    params.update(cfg["model"].get("extra") or {})
    return params


def extract_text(message) -> str:
    parts = []
    for block in getattr(message, "content", []) or []:
        if getattr(block, "type", None) == "text":
            parts.append(getattr(block, "text", ""))
    return "".join(parts)


def _norm(key: str) -> str:
    return " ".join(str(key).lower().replace("_", " ").split())


def _number(v) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ParseError(f"value {v!r} is not a number")
    v = float(v)
    if not (0.0 <= v <= 100.0):
        raise ParseError(f"value {v} is outside 0-100")
    return v


def parse_output(text: str) -> tuple[dict, dict]:
    """SPEC §6.3. Returns (probabilities, seen-notes). Raises ParseError."""
    decoder = json.JSONDecoder()
    obj = None
    for i, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            candidate, _ = decoder.raw_decode(text, i)
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict):
            obj = candidate
            break
    if obj is None:
        raise ParseError("no JSON object found")
    normalized = {_norm(k): v for k, v in obj.items()}
    probs, seen = {}, {}
    for f in FINDINGS:
        if _norm(f) not in normalized:
            raise ParseError(f"missing finding {f!r}")
        v = normalized[_norm(f)]
        if isinstance(v, dict):  # v1e format
            probs[f] = _number(v.get("p"))
            if "seen" in v:
                seen[f] = str(v["seen"])
        else:
            probs[f] = _number(v)
    return probs, seen


# ---------------------------------------------------------------- calls

def _usage(message) -> tuple[int, int]:
    u = getattr(message, "usage", None)
    return int(getattr(u, "input_tokens", 0) or 0), int(getattr(u, "output_tokens", 0) or 0)


def record_from_message(case_id, repeat, mode, message, attempts, prior_raw, usage, latency, error=None):
    rec = {
        "case_id": case_id, "repeat": repeat, "mode": mode, "attempts": attempts,
        "parse_ok": False, "probs": {}, "seen": {}, "raw_text": None, "prior_raw": prior_raw,
        "model": None, "stop_reason": None,
        "usage": {"input_tokens": usage[0], "output_tokens": usage[1]},
        "latency_s": round(latency, 3), "error": error, "ts_utc": utc_now(),
    }
    if message is not None:
        text = extract_text(message)
        rec["raw_text"] = text
        rec["model"] = getattr(message, "model", None)
        rec["stop_reason"] = getattr(message, "stop_reason", None)
        if error is None:
            try:
                rec["probs"], rec["seen"] = parse_output(text)
                rec["parse_ok"] = True
            except ParseError as exc:
                rec["error"] = f"parse: {exc}"
    return rec


def call_sync(client, params, case_id, repeat, parse_retries, mode) -> dict:
    attempts, prior, tin, tout = 0, [], 0, 0
    t0 = time.monotonic()
    while True:
        attempts += 1
        try:
            message = client.messages.create(**params)
        except Exception as exc:  # API error after SDK retries
            return record_from_message(case_id, repeat, mode, None, attempts, prior, (tin, tout),
                                       time.monotonic() - t0, error=f"api: {type(exc).__name__}: {exc}")
        i, o = _usage(message)
        tin, tout = tin + i, tout + o
        text = extract_text(message)
        try:
            parse_output(text)
            ok = True
        except ParseError:
            ok = False
        if ok or attempts > parse_retries:
            return record_from_message(case_id, repeat, mode, message, attempts, prior, (tin, tout),
                                       time.monotonic() - t0)
        prior.append(text)


# ---------------------------------------------------------------- run folder

def model_slug(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-." else "-" for c in name)


def make_identity(cfg, prompt_sha, lock, limit, repeats, mock_settings) -> tuple[str, dict]:
    obj = {
        "model": cfg["model"]["name"],
        "max_tokens": int(cfg["model"]["max_tokens"]),
        "extra": cfg["model"].get("extra") or {},
        "prompt_sha256": prompt_sha,
        "golden_lock_id": lock["lock_id"],
        "parse_retries": int(cfg["run"]["parse_retries"]),
        "limit": limit,
        "repeats": repeats,
        "mock": mock_settings,
    }
    return sha256_bytes(canonical_json(obj).encode("utf-8")), obj


def rebuild_predictions(run_dir: Path, case_ids: list[str], repeats: int) -> list[dict]:
    records = read_jsonl(run_dir / "responses.jsonl")
    best: dict[tuple, dict] = {}
    for rec in records:
        key = (rec["case_id"], rec["repeat"])
        if rec["parse_ok"] or key not in best or not best[key]["parse_ok"]:
            best[key] = rec
    rows = []
    for r in range(repeats):
        for cid in case_ids:
            rec = best.get((cid, r))
            row = {"case_id": cid, "repeat": r, "parse_ok": int(bool(rec and rec["parse_ok"]))}
            for f in FINDINGS:
                row[f] = rec["probs"][f] if rec and rec["parse_ok"] else ""
            rows.append(row)
    write_csv(run_dir / "predictions.csv", rows, ["case_id", "repeat", "parse_ok", *FINDINGS])
    return rows


# ---------------------------------------------------------------- main

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Blinded runner (SPEC §6, §11.2).")
    ap.add_argument("--golden", default="golden")
    ap.add_argument("--config", default="config.toml")
    ap.add_argument("--run-dir", default=None)
    ap.add_argument("--runs-root", default="runs")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--mode", choices=["sync", "batch"], default="sync")
    ap.add_argument("--mock", action="store_true", help="use the mock model (no API calls)")
    ap.add_argument("--mock-seed", type=int, default=0)
    ap.add_argument("--mock-noise", type=float, default=10.0)
    ap.add_argument("--mock-fail-rate", type=float, default=0.0)
    ap.add_argument("--show-request", action="store_true", help="print the request for the first case and exit")
    args = ap.parse_args(argv)

    load_dotenv(".env")
    cfg = load_config(args.config)
    golden_dir = Path(args.golden)
    lock, cases = load_public_golden(golden_dir)
    images_dir = public_golden_paths(golden_dir)["images"]
    if args.limit is not None:
        cases = cases[: args.limit]
    if not cases:
        die("no cases selected")

    prompt_path = Path(cfg["run"]["prompt"])
    if not prompt_path.exists():
        die(f"prompt file not found: {prompt_path}")
    prompt_bytes = prompt_path.read_bytes()
    prompt_text = prompt_bytes.decode("utf-8")
    prompt_sha = sha256_bytes(prompt_bytes)

    if args.show_request:
        params = build_request(cases[0], images_dir, prompt_text, cfg)
        for block in params["messages"][0]["content"]:
            if block["type"] == "image":
                d = block["source"]["data"]
                block["source"]["data"] = f"{d[:40]}…<{len(d)} base64 chars>"
        print(json.dumps(params, indent=2, ensure_ascii=False))
        return 0

    mock_settings = ({"seed": args.mock_seed, "noise": args.mock_noise, "fail_rate": args.mock_fail_rate}
                     if args.mock else None)
    identity, identity_obj = make_identity(cfg, prompt_sha, lock, args.limit, args.repeats, mock_settings)

    if args.run_dir:
        run_dir = Path(args.run_dir)
    else:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        tag = "mock" if args.mock else model_slug(cfg["model"]["name"])
        run_dir = Path(args.runs_root) / f"{stamp}_{prompt_path.stem}_{tag}"
    rc_path = run_dir / "run_config.json"
    if rc_path.exists():
        existing = read_json(rc_path)
        if existing.get("identity") != identity:
            die(f"{run_dir} belongs to a different run identity (settings, prompt, golden set, limit or repeats "
                f"differ). Start a new run folder instead.")
        print(f"Resuming {run_dir}")
    else:
        run_dir.mkdir(parents=True, exist_ok=True)
        if args.mock:
            sdk_version = "mock"
        else:
            try:
                import anthropic  # noqa: F401
                sdk_version = getattr(anthropic, "__version__", "unknown")
            except ImportError:
                die("the anthropic package is not installed: pip install -r requirements.txt")
        write_json(rc_path, {
            "identity": identity,
            "identity_obj": identity_obj,
            "harness_version": HARNESS_VERSION,
            "python": platform.python_version(),
            "sdk_version": sdk_version,
            "platform": platform.platform(),
            "created_utc": utc_now(),
            "golden_dir": str(golden_dir.resolve()),
            "golden_name": lock.get("name"),
            "golden_lock_id": lock["lock_id"],
            "prompt_path": str(prompt_path),
            "prompt_sha256": prompt_sha,
            "prompt_text": prompt_text,
            "repeats": args.repeats,
            "limit": args.limit,
            "case_ids": [c["case_id"] for c in cases],
            "config": cfg,
        })

    # client
    if args.mock:
        from .mock_model import MockClient
        client = MockClient(seed=args.mock_seed, noise=args.mock_noise, fail_rate=args.mock_fail_rate)
    else:
        try:
            import anthropic
        except ImportError:
            die("the anthropic package is not installed: pip install -r requirements.txt")
        if not os.environ.get("ANTHROPIC_API_KEY"):
            die("ANTHROPIC_API_KEY is not set (put it in .env)")
        client = anthropic.Anthropic(max_retries=int(cfg["run"]["api_max_retries"]))

    responses = run_dir / "responses.jsonl"
    done = {(r["case_id"], r["repeat"]) for r in read_jsonl(responses) if r["parse_ok"]}
    todo = [(c, r) for r in range(args.repeats) for c in cases if (c["case_id"], r) not in done]
    print(f"Run folder: {run_dir}")
    print(f"Cases: {len(cases)} × repeats: {args.repeats}  ·  already done: {len(done)}  ·  to do: {len(todo)}")

    write_lock = threading.Lock()

    def append(rec: dict) -> None:
        with write_lock:
            with open(responses, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    parse_retries = int(cfg["run"]["parse_retries"])
    mode_tag = "mock" if args.mock else args.mode

    if todo and args.mode == "sync":
        finished = 0

        def work(case: dict, rep: int) -> dict:
            # Build inside the worker so only `concurrency` requests (with base64 images) are in memory at once.
            return call_sync(client, build_request(case, images_dir, prompt_text, cfg),
                             case["case_id"], rep, parse_retries, mode_tag)

        with ThreadPoolExecutor(max_workers=int(cfg["run"]["concurrency"])) as pool:
            futures = {pool.submit(work, c, r): (c["case_id"], r) for c, r in todo}
            for fut in as_completed(futures):
                append(fut.result())
                finished += 1
                if finished % 10 == 0 or finished == len(todo):
                    print(f"  {finished}/{len(todo)} calls finished")
    elif args.mode == "batch":
        run_batch(client, todo, images_dir, prompt_text, cfg, run_dir, append,
                  "mock" if args.mock else "batch")

    rows = rebuild_predictions(run_dir, [c["case_id"] for c in cases], args.repeats)
    failed = sum(1 for row in rows if not row["parse_ok"])
    print(f"Done. {len(rows) - failed}/{len(rows)} (case, repeat) pairs parsed.")
    if failed:
        hint = " → rerun with --mode sync on the same --run-dir to retry them" if args.mode == "batch" else \
            " → rerun the same command with --run-dir to retry them"
        print(f"{failed} failed{hint}")
    print(f"Next: python -m harness.score {run_dir}")
    return 0


def run_batch(client, todo, images_dir, prompt_text, cfg, run_dir, append, mode_tag) -> None:
    state_path = run_dir / "batches.json"
    state = read_json(state_path) if state_path.exists() else {"batches": []}
    pending = [b for b in state["batches"] if not b["collected"]]

    if not pending and todo:
        limit_bytes = int(cfg["run"]["batch_max_mb"]) * 1024 * 1024
        chunk, size = [], 0

        def submit(requests):
            batch = client.messages.batches.create(requests=requests)
            state["batches"].append({"id": batch.id, "custom_ids": [q["custom_id"] for q in requests],
                                     "collected": False, "submitted_utc": utc_now()})
            write_json(state_path, state)
            print(f"  submitted batch {batch.id} with {len(requests)} requests")

        for case, rep in todo:
            req = {"custom_id": f"{case['case_id']}-r{rep}",
                   "params": build_request(case, images_dir, prompt_text, cfg)}
            req_size = len(json.dumps(req))
            if chunk and size + req_size > limit_bytes:
                submit(chunk)
                chunk, size = [], 0
            chunk.append(req)
            size += req_size
        if chunk:
            submit(chunk)
        pending = [b for b in state["batches"] if not b["collected"]]

    poll = int(cfg["run"].get("poll_seconds", 60))
    for b in pending:
        while True:
            status = client.messages.batches.retrieve(b["id"])
            if status.processing_status == "ended":
                break
            print(f"  batch {b['id']}: {status.processing_status}; checking again in {poll}s")
            time.sleep(poll)
        for entry in client.messages.batches.results(b["id"]):
            case_id, rep = entry.custom_id.rsplit("-r", 1)
            result = entry.result
            if result.type == "succeeded":
                msg = result.message
                rec = record_from_message(case_id, int(rep), mode_tag, msg, 1, [], _usage(msg), 0.0)
            else:
                rec = record_from_message(case_id, int(rep), mode_tag, None, 1, [], (0, 0), 0.0,
                                          error=f"batch result: {result.type}")
            append(rec)
        b["collected"] = True
        write_json(state_path, state)
        print(f"  collected batch {b['id']}")


if __name__ == "__main__":
    sys.exit(main())
