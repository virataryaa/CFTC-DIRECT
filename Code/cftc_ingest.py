"""
Hardmine — COT CFTC Weekly Ingest (CFTC Socrata API)
======================================================
Incremental companion to cftc_backfill.py — meant to run weekly (Friday,
after the 15:30 ET CFTC release). Re-fetches only the current report-year for
each dataset, since CFTC revises prior weeks in place within a year, then
merges and dedups into the existing parquet files rather than re-pulling all
of history every run.

All commodity config, field maps, fetch and reshape logic are imported from
cftc_backfill.py — nothing is duplicated here.

Usage:
    python cftc_ingest.py             # incremental (default)
    python cftc_ingest.py --full      # full-history rebuild
    python cftc_ingest.py --merge-px  # also refresh Px from LSEG/COT_ALL
"""

import argparse
import datetime
import logging
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import cftc_backfill as backfill  # reuse config + fetch + reshape, no duplication

LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / "cftc_ingest.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)


def incremental_start(path: Path) -> str:
    """Re-fetch from the start of the latest year on file, so CFTC's in-year
    revisions to earlier weeks are picked up rather than frozen at first print."""
    latest = pd.to_datetime(pd.read_parquet(path, columns=["Date"])["Date"]).max()
    return "%d-01-01" % latest.year


def merge_and_dedup(old: pd.DataFrame, new: pd.DataFrame, keys: list) -> pd.DataFrame:
    """New rows win on a key collision — that is what applies a CFTC revision."""
    merged = pd.concat([old, new], ignore_index=True)
    before = len(merged)
    merged = merged.drop_duplicates(subset=keys, keep="last")
    merged = merged.sort_values(keys).reset_index(drop=True)
    log.info("  Dedup: %d -> %d rows (-%d)", before, len(merged), before - len(merged))
    return merged


def run_one(label: str, path: Path, dataset: str, codes: list, lookup: dict,
            keys: list, builder, session, full: bool, merge_px: bool) -> None:
    log.info("--- %s ---", label)

    if full or not path.exists():
        start = backfill.START_FULL
        log.info("%s: full history from %s",
                 "Rebuild requested" if full else "No existing file", start)
    else:
        start = incremental_start(path)
        log.info("Incremental from %s", start)

    try:
        new_df = builder(backfill.fetch_dataset(dataset, codes, start, session), lookup)
    except Exception as exc:
        log.error("  ERROR fetching %s: %s", label, exc)
        return

    if new_df.empty:
        log.warning("  No %s rows returned — leaving existing file untouched.", label)
        return

    if path.exists() and not full:
        final = merge_and_dedup(pd.read_parquet(path), new_df, keys)
    else:
        final = new_df.sort_values(keys).reset_index(drop=True)

    if merge_px:
        final = backfill.merge_px(final, path.name)

    final.to_parquet(path, engine="pyarrow", index=False)
    log.info("%s saved -> %s | %d rows | %s -> %s",
             label, path.name, len(final),
             final["Date"].min().date(), final["Date"].max().date())


def main() -> int:
    ap = argparse.ArgumentParser(description="COT CFTC weekly ingest.")
    ap.add_argument("--full", action="store_true",
                    help="full-history rebuild instead of an incremental top-up")
    ap.add_argument("--merge-px", action="store_true",
                    help="fill Px from the sibling LSEG/COT_ALL parquets")
    args = ap.parse_args()

    log.info("=" * 70)
    log.info("COT CFTC Ingest  |  %s  |  mode=%s",
             datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
             "FULL" if args.full else "INCREMENTAL")

    backfill.DB_DIR.mkdir(parents=True, exist_ok=True)
    session = backfill._session()

    disagg_codes = list(backfill.DISAGG_COMMODITIES.values())
    cit_codes = list(backfill.CIT_COMMODITIES.values())
    disagg_lookup = {v: k for k, v in backfill.DISAGG_COMMODITIES.items()}
    cit_lookup = {v: k for k, v in backfill.CIT_COMMODITIES.items()}

    disagg_keys = ["Commodity", "Crop", "Date"]
    cit_keys = ["Commodity", "Date"]

    def futopt_builder(raw, lookup):
        return backfill.build_disagg(raw, lookup, backfill.DISAGG_FUTOPT_OI_DTYPE)

    def fut_builder(raw, lookup):
        return backfill.build_disagg(raw, lookup, backfill.DISAGG_FUT_OI_DTYPE)

    run_one("Disagg FutOpt", backfill.DISAGG_FUTOPT_FILE,
            backfill.DATASET_DISAGG_FUTOPT, disagg_codes, disagg_lookup,
            disagg_keys, futopt_builder, session, args.full, args.merge_px)

    run_one("Disagg Fut", backfill.DISAGG_FUT_FILE,
            backfill.DATASET_DISAGG_FUT, disagg_codes, disagg_lookup,
            disagg_keys, fut_builder, session, args.full, args.merge_px)

    run_one("CIT", backfill.CIT_FILE,
            backfill.DATASET_CIT, cit_codes, cit_lookup,
            cit_keys, backfill.build_cit, session, args.full, args.merge_px)

    legacy_codes = list(backfill.LEGACY_COMMODITIES.values())
    legacy_lookup = {v: k for k, v in backfill.LEGACY_COMMODITIES.items()}

    run_one("Legacy FutOpt", backfill.LEGACY_FUTOPT_FILE,
            backfill.DATASET_LEGACY_FUTOPT, legacy_codes, legacy_lookup,
            disagg_keys, backfill.build_legacy, session, args.full, args.merge_px)

    run_one("Legacy Fut", backfill.LEGACY_FUT_FILE,
            backfill.DATASET_LEGACY_FUT, legacy_codes, legacy_lookup,
            disagg_keys, backfill.build_legacy, session, args.full, args.merge_px)

    log.info("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
