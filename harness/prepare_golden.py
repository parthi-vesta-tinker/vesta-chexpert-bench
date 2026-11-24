"""Build a frozen, blinded golden set from a CheXpert-format reference CSV and an image folder (SPEC §4, §7, §11.2).

Example:
    python -m harness.prepare_golden --labels data/valid_labels.csv --image-root data/images \
        --out golden --name chexpert-valid-200 --expect-studies 200 --expect-images 234
"""
from __future__ import annotations

import argparse
import random
import re
import shutil
import sys
from collections import defaultdict
from pathlib import Path

from .common import (
    FINDINGS,
    HARNESS_VERSION,
    MANIFEST_COLUMNS,
    PRIMARY,
    lock_id_for,
    public_golden_paths,
    read_csv,
    sealed_golden_paths,
    sha256_bytes,
    sha256_file,
    utc_now,
    write_csv,
    write_json,
)
from .imaging import RENDER_RECIPE, prepare_image

STEM_RE = re.compile(r"(train|valid|test)/(patient\d+)/(study\d+)/(view\d+_[A-Za-z]+)")


class PrepError(Exception):
    pass


def stem_key(path_str: str) -> str:
    """'<split>/patientN/studyM/viewK_<frontal|lateral>' with leading folders and extension removed."""
    p = path_str.replace("\\", "/")
    m = STEM_RE.search(p)
    if m:
        return "/".join(m.groups())
    parts = [x for x in p.split("/") if x]
    if not parts:
        return ""
    parts[-1] = parts[-1].rsplit(".", 1)[0]
    return "/".join(parts[-4:])


def parse_value(raw: str) -> int:
    s = (raw or "").strip()
    if s == "":
        raise PrepError("blank")
    try:
        v = float(s)
    except ValueError as exc:
        raise PrepError(f"not a number: {s!r}") from exc
    if v == 1.0:
        return 1
    if v == 0.0:
        return 0
    if v == -1.0:
        raise PrepError("uncertain (-1)")
    raise PrepError(f"unexpected value {s!r}")


def infer_view(row: dict, view_col: str, path_str: str) -> str:
    v = (row.get(view_col) or "").strip().lower()
    if v in ("frontal", "lateral"):
        return v
    name = path_str.lower()
    if "frontal" in name:
        return "frontal"
    if "lateral" in name:
        return "lateral"
    return "unknown"


def index_images(image_root: Path, ext_order: list[str]) -> dict[str, dict[str, list[Path]]]:
    """stem -> extension -> [paths]"""
    index: dict[str, dict[str, list[Path]]] = defaultdict(lambda: defaultdict(list))
    exts = set(ext_order)
    for path in image_root.rglob("*"):
        if path.is_file() and path.suffix.lower() in exts:
            rel = path.relative_to(image_root).as_posix()
            index[stem_key(rel)][path.suffix.lower()].append(path)
    return index


def resolve(stem: str, index, ext_order: list[str]) -> Path:
    by_ext = index.get(stem)
    if not by_ext:
        raise PrepError(f"no image found for {stem}")
    for ext in ext_order:
        paths = by_ext.get(ext, [])
        if len(paths) == 1:
            return paths[0]
        if len(paths) > 1:
            listing = ", ".join(str(p) for p in paths)
            raise PrepError(f"{len(paths)} images share stem {stem} and extension {ext}: {listing}")
    raise PrepError(f"no image with an allowed extension for {stem}")


def build(args) -> int:
    labels_csv = Path(args.labels)
    image_root = Path(args.image_root)
    out = Path(args.out)
    ext_order = [e.strip().lower() if e.strip().startswith(".") else "." + e.strip().lower()
                 for e in args.ext_order.split(",") if e.strip()]

    if not labels_csv.exists():
        raise PrepError(f"reference CSV not found: {labels_csv}")
    if not image_root.is_dir():
        raise PrepError(f"image root not found: {image_root}")
    if out.exists() and any(out.iterdir()):
        if not args.force:
            raise PrepError(f"{out} already exists and is not empty. A golden set is never edited; "
                            f"use a new --out folder, or --force to delete and rebuild it.")
        shutil.rmtree(out)

    fieldnames, rows = read_csv(labels_csv)
    missing_cols = [c for c in [args.path_col, *FINDINGS] if c not in fieldnames]
    if missing_cols:
        raise PrepError(f"reference CSV is missing columns: {missing_cols}")
    if not rows:
        raise PrepError("reference CSV has no rows")

    # 1. Parse reference values with the label guard (SPEC §4).
    problems = []
    parsed = []
    study_re = re.compile(args.study_regex)
    for i, row in enumerate(rows, start=2):  # header is line 1
        path_str = row[args.path_col]
        values = {}
        for f in FINDINGS:
            try:
                values[f] = parse_value(row.get(f, ""))
            except PrepError as exc:
                problems.append(f"line {i} {f}: {exc}")
        stem = stem_key(path_str)
        m = study_re.search(path_str.replace("\\", "/"))
        split = stem.split("/")[0] if stem.count("/") >= 3 else ""
        study_id = (f"{split}/" if split else "") + (m.group(1) if m else "/".join(stem.split("/")[:-1]))
        parsed.append({"path": path_str, "stem": stem, "study": study_id, "values": values,
                       "view": infer_view(row, args.view_col, path_str)})
    if problems:
        shown = "\n  ".join(problems[:20])
        more = f"\n  ... and {len(problems) - 20} more" if len(problems) > 20 else ""
        raise PrepError("label guard failed: uncertain (-1), blank or invalid values found. This usually means "
                        "report-derived labels, not the radiologist reference standard.\n  " + shown + more)

    # 2. Study-level consistency.
    studies: dict[str, list[dict]] = defaultdict(list)
    for p in parsed:
        studies[p["study"]].append(p)
    for sid, items in studies.items():
        first = items[0]["values"]
        if any(it["values"] != first for it in items[1:]):
            raise PrepError(f"study {sid} has rows that disagree on reference values")

    # 3. Resolve every row to exactly one image by path stem.
    index = index_images(image_root, ext_order)
    errors, used = [], {}
    for p in parsed:
        try:
            p["src"] = resolve(p["stem"], index, ext_order)
        except PrepError as exc:
            errors.append(str(exc))
            continue
        if p["src"] in used:
            errors.append(f"image {p['src']} matched by two reference rows ({used[p['src']]} and {p['path']})")
        used[p["src"]] = p["path"]
    if errors:
        shown = "\n  ".join(errors[:20])
        more = f"\n  ... and {len(errors) - 20} more" if len(errors) > 20 else ""
        raise PrepError("join failed:\n  " + shown + more)

    n_studies, n_images = len(studies), len(parsed)
    if args.expect_studies is not None and n_studies != args.expect_studies:
        raise PrepError(f"join check: expected {args.expect_studies} studies, found {n_studies}")
    if args.expect_images is not None and n_images != args.expect_images:
        raise PrepError(f"join check: expected {args.expect_images} images, found {n_images}")

    # 4. Shuffle studies with the seed and assign opaque case IDs.
    study_ids = sorted(studies)
    random.Random(args.seed).shuffle(study_ids)
    width = max(4, len(str(len(study_ids))))

    pub = public_golden_paths(out)
    sealed = sealed_golden_paths(out)
    pub["images"].mkdir(parents=True, exist_ok=True)
    sealed["dir"].mkdir(parents=True, exist_ok=True)

    manifest_rows, truth_rows, source_rows, all_hashes = [], [], [], []
    for n, sid in enumerate(study_ids, start=1):
        case_id = f"case_{n:0{width}d}"
        items = sorted(studies[sid], key=lambda it: (it["view"] != "frontal", it["stem"]))
        names, views, hashes = [], [], []
        for k, it in enumerate(items, start=1):
            name = f"{case_id}_{k}.png"
            dst = pub["images"] / name
            prepare_image(it["src"], dst, args.max_long_edge, args.max_visual_tokens)
            h = sha256_file(dst)
            names.append(name)
            views.append(it["view"])
            hashes.append(h)
            all_hashes.append(h)
        manifest_rows.append({"case_id": case_id, "images": ";".join(names), "views": ";".join(views),
                              "sha256": ";".join(hashes)})
        truth_rows.append({"case_id": case_id, **items[0]["values"]})
        source_rows.append({"case_id": case_id, "study_id": sid,
                            "source_paths": ";".join(str(it["src"]) for it in items),
                            "reference_paths": ";".join(it["path"] for it in items)})

    write_csv(pub["manifest"], manifest_rows, MANIFEST_COLUMNS)
    write_csv(sealed["truth"], truth_rows, ["case_id", *FINDINGS])
    write_csv(sealed["source_map"], source_rows, ["case_id", "study_id", "source_paths", "reference_paths"])

    prevalence = {f: {"positive": sum(r[f] for r in truth_rows), "n": len(truth_rows)} for f in FINDINGS}
    write_json(sealed["summary"], {"n_cases": n_studies, "n_images": n_images, "prevalence": prevalence})

    lock = {
        "name": args.name,
        "harness_version": HARNESS_VERSION,
        "created_utc": utc_now(),
        "n_cases": n_studies,
        "n_images": n_images,
        "prep": {
            "max_long_edge": args.max_long_edge,
            "max_visual_tokens": args.max_visual_tokens,
            "seed": args.seed,
            "study_regex": args.study_regex,
            "ext_order": ext_order,
            "render_recipe": RENDER_RECIPE,
            "reference_csv_sha256": sha256_file(labels_csv),
        },
        "manifest_sha256": sha256_file(pub["manifest"]),
        "labels_sha256": sha256_file(sealed["truth"]),
        "images_sha256": sha256_bytes(";".join(all_hashes).encode("utf-8")),
    }
    lock["lock_id"] = lock_id_for(lock)
    write_json(pub["lock"], lock)

    print(f"Golden set '{args.name}' written to {out}")
    print(f"  studies: {n_studies}   images: {n_images}   lock_id: {lock['lock_id'][:16]}…")
    print("  prevalence:")
    for f in FINDINGS:
        tag = "" if f in PRIMARY else " (secondary)"
        print(f"    {f:<17}{tag:<12} {prevalence[f]['positive']:>4}/{prevalence[f]['n']}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build a frozen, blinded golden set (SPEC §4, §7).")
    ap.add_argument("--labels", required=True, help="reference CSV in CheXpert valid.csv / val_labels.csv format")
    ap.add_argument("--image-root", required=True, help="folder holding the images (any depth)")
    ap.add_argument("--out", default="golden")
    ap.add_argument("--name", default="chexpert-valid-200")
    ap.add_argument("--path-col", default="Path")
    ap.add_argument("--view-col", default="Frontal/Lateral")
    ap.add_argument("--study-regex", default=r"(patient\d+/study\d+)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--max-long-edge", type=int, default=2576)
    ap.add_argument("--max-visual-tokens", type=int, default=4784)
    ap.add_argument("--ext-order", default=".dcm,.png,.jpg")
    ap.add_argument("--expect-studies", type=int, default=None)
    ap.add_argument("--expect-images", type=int, default=None)
    ap.add_argument("--force", action="store_true", help="delete an existing --out folder and rebuild")
    args = ap.parse_args(argv)
    try:
        return build(args)
    except PrepError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
