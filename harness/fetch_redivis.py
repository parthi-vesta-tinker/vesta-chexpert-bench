"""Step 0 helper for Redivis (SPEC §13). UNVERIFIED: written without access to Redivis.

The Redivis Python client API used here (redivis.organization(...).dataset(...), list_tables(),
table(...).to_pandas_dataframe(), redivis.file(...).download(...)) is from memory of the client's
documentation and has not been tested against the CheXpert Plus dataset. Run `list` first; if a call
fails, fix this file against the current Redivis Python docs (https://apidocs.redivis.com/).

Needs: pip install redivis pandas, and REDIVIS_API_TOKEN in .env.

Examples:
    python -m harness.fetch_redivis list --org StanfordAIMI --dataset <dataset name or reference>
    python -m harness.fetch_redivis export-table df_chexpert_plus_240401 --out data/df.csv \
        --org StanfordAIMI --dataset <ref> --filter-col path_to_image --contains valid/
    python -m harness.fetch_redivis download-files --index data/dicom_valid.csv --file-id-col file_id --out data/images
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .common import load_dotenv


def _client():
    load_dotenv(".env")
    if not os.environ.get("REDIVIS_API_TOKEN"):
        sys.exit("ERROR: REDIVIS_API_TOKEN is not set (put it in .env)")
    try:
        import redivis
    except ImportError:
        sys.exit("ERROR: the redivis package is not installed: pip install redivis pandas")
    return redivis


def _dataset(redivis, args):
    owner = redivis.organization(args.org) if args.owner_type == "org" else redivis.user(args.org)
    return owner.dataset(args.dataset)


def cmd_list(args) -> int:
    redivis = _client()
    ds = _dataset(redivis, args)
    tables = ds.list_tables()
    print(f"{len(tables)} tables/file indexes in {args.org}/{args.dataset}:")
    for t in tables:
        props = getattr(t, "properties", None) or {}
        name = getattr(t, "name", None) or props.get("name")
        rows = props.get("numRows")
        size = props.get("numBytes")
        print(f"- {name}  rows={rows}  bytes={size}")
        try:
            variables = t.list_variables()
            cols = [getattr(v, "name", None) or (getattr(v, "properties", {}) or {}).get("name") for v in variables]
            print(f"    columns: {cols}")
        except Exception as exc:  # unknown client surface
            print(f"    (could not list columns: {type(exc).__name__}: {exc})")
    return 0


def cmd_export_table(args) -> int:
    redivis = _client()
    ds = _dataset(redivis, args)
    df = ds.table(args.table).to_pandas_dataframe(max_results=args.max_results)
    if args.filter_col and args.contains:
        df = df[df[args.filter_col].astype(str).str.contains(args.contains, regex=False)]
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.out, index=False)
    print(f"wrote {len(df)} rows to {args.out}")
    return 0


def cmd_download_files(args) -> int:
    redivis = _client()
    import csv
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    with open(args.index, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for i, row in enumerate(rows, start=1):
        file_id = row[args.file_id_col]
        dest = out
        if args.path_col and row.get(args.path_col):
            dest = out / Path(row[args.path_col]).parent  # keep valid/patient…/study… structure
            dest.mkdir(parents=True, exist_ok=True)
        redivis.file(file_id).download(str(dest))
        if i % 10 == 0 or i == len(rows):
            print(f"  {i}/{len(rows)} files")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Redivis Step 0 helper (UNVERIFIED; see module docstring).")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--org", default="StanfordAIMI", help="Redivis organization or user that owns the dataset")
        p.add_argument("--owner-type", choices=["org", "user"], default="org")
        p.add_argument("--dataset", required=True, help="dataset name/reference as shown in Redivis")

    p = sub.add_parser("list")
    common(p)
    p.set_defaults(fn=cmd_list)

    p = sub.add_parser("export-table")
    common(p)
    p.add_argument("table")
    p.add_argument("--out", required=True)
    p.add_argument("--max-results", type=int, default=None)
    p.add_argument("--filter-col", default=None)
    p.add_argument("--contains", default=None)
    p.set_defaults(fn=cmd_export_table)

    p = sub.add_parser("download-files")
    p.add_argument("--index", required=True, help="CSV exported from a file index table")
    p.add_argument("--file-id-col", required=True)
    p.add_argument("--path-col", default=None, help="column holding the original relative path, to keep folders")
    p.add_argument("--out", required=True)
    p.set_defaults(fn=cmd_download_files)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
