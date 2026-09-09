"""
Hardmine — ICE Futures Europe COT ingest (London softs)
========================================================
Fills the one gap the CFTC cannot: RC (Robusta Coffee), LCC (London Cocoa)
and LSU (White Sugar). These trade on ICE Futures Europe, a UK-regulated
venue, so the CFTC has no reporting authority over them and they appear in
none of its datasets.

ICE publishes its own COT for them, free and unauthenticated, explicitly
modelled on "the CFTC Long Format Disaggregated COT" (their words) so the
column layout drops straight into our schema. Tuesday snapshot, published
Friday 18:30 London.

Source — one CSV per year, all contracts in each:
    https://www.ice.com/publicdocs/futures/COTHist{YYYY}.csv

The current year's file is overwritten in place every Friday, accumulating
the year, so a weekly update is a single download. Rows are written into the
same two parquets the CFTC ingest maintains:

    Database/cot_disagg_futopt.parquet   <- ICE "Combined" rows
    Database/cot_disagg_fut.parquet      <- ICE "FutOnly" rows

Usage:
    python ice_ingest.py                 # weekly: current year (+ prior in Jan/Feb)
    python ice_ingest.py --full          # rebuild all ICE rows from 2014
    python ice_ingest.py --start 2020    # from a given year
"""

import argparse
import datetime
import io
import json
import logging
import re
import sys
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).parent))
import cftc_backfill as backfill  # schema, column lists and _add_pct

LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / "ice_ingest.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

URL = "https://www.ice.com/publicdocs/futures/COTHist{year}.csv"
ETAG_FILE = backfill.DB_DIR / ".ice_etags.json"

# The softs only enter these files in 2014. COTHist2011-2013 carry Brent and
# Gasoil alone, and the pre-ICE LIFFE softs history (2012-05 to 2014-09) lives
# in LIFFE_COT_Hist.csv under a different 28-column layout, not read here.
FIRST_YEAR = 2014

# ICE gives softs no CFTC_Contract_Market_Code (it is blank), so contracts are
# identified by name. Matching on a keyword rather than the full string on
# purpose: ICE's own header has a typo in one of them, "ICE White Sugar
# Futures and Options- ICE Futures Europe", with the space before the dash
# missing.
NAME_TO_COMMODITY = {
    "Robusta": "RC",
    "Cocoa": "LCC",
    "White Sugar": "LSU",
}

# ICE's column names are the CFTC "human" names and follow a strict
# <Base>_All / _Old / _Other pattern, so the maps are derived from base names
# rather than spelled out per crop the way CFTC's irregular API names force.
POS_BASE = {
    "Total OI":       "Open_Interest",
    "Producer Long":  "Prod_Merc_Positions_Long",
    "Producer Short": "Prod_Merc_Positions_Short",
    "Swap Long":      "Swap_Positions_Long",
    "Swap Short":     "Swap_Positions_Short",
    "Swap Spread":    "Swap_Positions_Spread",
    "MM Long":        "M_Money_Positions_Long",
    "MM Short":       "M_Money_Positions_Short",
    "MM Spread":      "M_Money_Positions_Spread",
    "Other Long":     "Other_Rept_Positions_Long",
    "Other Short":    "Other_Rept_Positions_Short",
    "Other Spread":   "Other_Rept_Positions_Spread",
    "Tot Rept Long":  "Tot_Rept_Positions_Long",
    "Tot Rept Short": "Tot_Rept_Positions_Short",
    "Non Rep Long":   "NonRept_Positions_Long",
    "Non Rep Short":  "NonRept_Positions_Short",
}
TRADERS_BASE = {
    "Traders Total":          "Traders_Tot",
    "Traders Producer Long":  "Traders_Prod_Merc_Long",
    "Traders Producer Short": "Traders_Prod_Merc_Short",
    "Traders Swap Long":      "Traders_Swap_Long",
    "Traders Swap Short":     "Traders_Swap_Short",
    "Traders Swap Spread":    "Traders_Swap_Spread",
    "Traders MM Long":        "Traders_M_Money_Long",
    "Traders MM Short":       "Traders_M_Money_Short",
    "Traders MM Spread":      "Traders_M_Money_Spread",
    "Traders Other Long":     "Traders_Other_Rept_Long",
    "Traders Other Short":    "Traders_Other_Rept_Short",
    "Traders Other Spread":   "Traders_Other_Rept_Spread",
    "Traders Tot Rept Long":  "Traders_Tot_Rept_Long",
    "Traders Tot Rept Short": "Traders_Tot_Rept_Short",
}


# ==============================================================================
# FETCH
# ==============================================================================
def _norm(col: str) -> str:
    """Normalise an ICE column name.

    ICE is not consistent across years: up to and including 2025 the swap
    fields are spelled with a doubled underscore ("Swap__Positions_Short_All")
    and from 2026 with a single one. Collapsing runs of underscores makes both
    vintages land on the same name, so Swap Short / Swap Spread do not
    silently become NaN for the older files. Also drops the UTF-8 BOM that
    appears on the first column of the 2026 file.
    """
    return re.sub(r"_+", "_", col.replace("﻿", "").strip())


def _load_etags() -> dict:
    if ETAG_FILE.exists():
        try:
            return json.loads(ETAG_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_etags(tags: dict) -> None:
    ETAG_FILE.write_text(json.dumps(tags, indent=2), encoding="utf-8")


def fetch_year(year: int, etags: dict, session: requests.Session):
    """Download one yearly CSV. Returns None when ICE reports it unchanged.

    The ETag check is what makes a weekly run cheap and lets the job tell
    'nothing published yet' apart from 'published but empty'."""
    url = URL.format(year=year)
    headers = {}
    if str(year) in etags:
        headers["If-None-Match"] = etags[str(year)]

    r = session.get(url, headers=headers, timeout=180)
    if r.status_code == 304:
        log.info("  %d: unchanged (304)", year)
        return None
    if r.status_code == 404:
        log.warning("  %d: not published (404)", year)
        return None
    r.raise_for_status()

    if r.headers.get("ETag"):
        etags[str(year)] = r.headers["ETag"]
    # utf-8-sig, not r.text: the 2026 file carries a BOM that would otherwise
    # ride along on the first column name and stop it matching.
    df = pd.read_csv(io.StringIO(r.content.decode("utf-8-sig")), low_memory=False)
    df.columns = [_norm(c) for c in df.columns]
    log.info("  %d: %d rows (modified %s)", year, len(df),
             r.headers.get("Last-Modified", "?"))
    return df


# ==============================================================================
# TRANSFORM
# ==============================================================================
def _num(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series(pd.NA, index=df.index, dtype="Float64")
    s = df[col]
    if s.dtype == object:                      # some years quote thousands
        s = s.astype(str).str.replace(",", "", regex=False)
    return pd.to_numeric(s, errors="coerce").astype("Float64")


def build(raw: pd.DataFrame, flavour: str, oi_dtype: str) -> pd.DataFrame:
    """Reshape ICE rows of one flavour ('FutOnly'/'Combined') into the
    project's 57-column disaggregated schema.

    Only Crop="All" rows are produced. ICE's _Old columns are NOT an old-crop
    split: they hold the previous week's _All values (verified — they match
    the prior row exactly, 100% of the time), evidently so the sheet can
    compute week-on-week change. Writing them into Crop="Old" would silently
    pass last week's numbers off as old-crop data. _Other is entirely blank.
    """
    sub = raw[raw["FutOnly_or_Combined"] == flavour].copy()
    if sub.empty:
        return pd.DataFrame(columns=backfill.DISAGG_FINAL_COLS)

    # ICE has renamed columns between vintages before (the swap double
    # underscore). Say so loudly rather than emitting a column of NaN.
    missing = [b + "_All" for b in list(POS_BASE.values()) + list(TRADERS_BASE.values())
               if b + "_All" not in sub.columns]
    if missing:
        log.error("  %s: %d expected ICE columns absent -> these map to NaN: %s",
                  flavour, len(missing), ", ".join(missing))

    names = sub["Market_and_Exchange_Names"].astype(str)
    commodity = pd.Series(pd.NA, index=sub.index, dtype="object")
    for key, code in NAME_TO_COMMODITY.items():
        commodity = commodity.mask(names.str.contains(key, case=False, na=False), code)

    out = pd.DataFrame({
        "Commodity": commodity,
        "Crop": "All",
        "Date": pd.to_datetime(sub["As_of_Date_Form_MM/DD/YYYY"],
                               errors="coerce").dt.normalize(),
    })
    for col, base in POS_BASE.items():
        out[col] = _num(sub, base + "_All")
    for col, base in TRADERS_BASE.items():
        out[col] = _num(sub, base + "_All")

    # ICE leaves Tot_Rept_Positions_* blank for the softs, so build it from the
    # categories. Verified against the alternative route (Open Interest minus
    # Non-Reportable, which is how ICE defines the balancing figure): the two
    # agree on 100% of rows, max difference 0. Deriving from the components
    # instead of from OI keeps the "OI == Tot Rept + Non Rep" identity an
    # independent check rather than something true by construction.
    for side in ("Long", "Short"):
        out["Tot Rept " + side] = (
            out["Producer " + side] + out["Swap " + side]
            + out["MM " + side] + out["Other " + side]
            + out["Swap Spread"] + out["MM Spread"] + out["Other Spread"]
        )

    # Traders_Tot_Rept_* is likewise blank in ICE's file and is deliberately
    # left NaN. It could be faked as the sum of the four category counts —
    # which is what LSEG/COT_ALL does — but that quantity means something
    # different from the true distinct trader count the CFTC rows in this same
    # column carry, so filling it would mix two definitions in one column.
    # ICE computes concentration for its energy contracts only, so these stay
    # NaN for the softs — the same gap LSEG/COT_ALL has.
    for col in backfill.DISAGG_CONC_COLS:
        out[col] = pd.Series(pd.NA, index=out.index, dtype="Float64")

    backfill._add_pct(out, backfill.DISAGG_POS_COLS)
    out["Px"] = pd.Series(pd.NA, index=out.index, dtype="Float64")

    out = out.dropna(subset=["Commodity", "Date"])
    out = out.drop_duplicates(subset=["Commodity", "Crop", "Date"], keep="last")
    out = out[backfill.DISAGG_FINAL_COLS]

    out["Total OI"] = out["Total OI"].round().astype(oi_dtype)
    for c in backfill.DISAGG_POS_COLS + ["Traders Total",
                                         "Traders Tot Rept Long",
                                         "Traders Tot Rept Short"]:
        out[c] = out[c].round().astype("Int64")
    for c in backfill.DISAGG_TRADER_CAT_COLS + backfill.DISAGG_CONC_COLS:
        out[c] = out[c].astype("float64")

    return out.sort_values(["Commodity", "Crop", "Date"]).reset_index(drop=True)


# ==============================================================================
# MERGE
# ==============================================================================
KEYS = ["Commodity", "Crop", "Date"]


def upsert(path: Path, new: pd.DataFrame, label: str) -> None:
    """Replace this run's ICE rows in the parquet, leaving CFTC rows alone.

    Keyed on (Commodity, Crop, Date) with new rows winning, so an ICE revision
    to an existing week overwrites it rather than duplicating."""
    if new.empty:
        log.warning("  %s: no ICE rows built — file untouched.", label)
        return

    if path.exists():
        old = pd.read_parquet(path)
        merged = pd.concat([old, new], ignore_index=True)
        before = len(merged)
        merged = merged.drop_duplicates(subset=KEYS, keep="last")
        log.info("  %s: %d existing + %d ICE -> %d rows (-%d dupes)",
                 label, len(old), len(new), len(merged), before - len(merged))
    else:
        merged = new
        log.info("  %s: creating new file with %d ICE rows", label, len(new))

    merged = merged.sort_values(KEYS).reset_index(drop=True)
    merged.to_parquet(path, engine="pyarrow", index=False)

    ice = merged[merged["Commodity"].isin(NAME_TO_COMMODITY.values())]
    log.info("  %s saved | %d rows total | ICE rows %d | %s -> %s",
             path.name, len(merged), len(ice),
             ice["Date"].min().date(), ice["Date"].max().date())


def years_to_fetch(full: bool, start: int | None) -> list:
    today = datetime.date.today()
    if start:
        return list(range(start, today.year + 1))
    if full:
        return list(range(FIRST_YEAR, today.year + 1))
    # Weekly: the current year is enough, except early in the year — ICE
    # finalises the prior year's file days into January (2025's last write was
    # 2026-01-05), so keep pulling it until the revision window has closed.
    years = [today.year]
    if today.month <= 2:
        years.insert(0, today.year - 1)
    return years


def main() -> int:
    ap = argparse.ArgumentParser(description="Ingest ICE Futures Europe COT (RC/LCC/LSU).")
    ap.add_argument("--full", action="store_true", help="rebuild from %d" % FIRST_YEAR)
    ap.add_argument("--start", type=int, help="first year to fetch")
    ap.add_argument("--force", action="store_true",
                    help="ignore stored ETags and re-download")
    args = ap.parse_args()

    log.info("=" * 70)
    log.info("ICE COT Ingest  |  %s  |  %s",
             datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
             "FULL" if (args.full or args.start) else "WEEKLY")

    backfill.DB_DIR.mkdir(parents=True, exist_ok=True)
    etags = {} if args.force else _load_etags()
    session = requests.Session()

    years = years_to_fetch(args.full, args.start)
    log.info("Years: %s", ", ".join(str(y) for y in years))

    frames = []
    for y in years:
        try:
            df = fetch_year(y, etags, session)
        except Exception as exc:
            log.error("  %d: fetch failed — %s", y, str(exc)[:150])
            continue
        if df is not None:
            frames.append(df)

    _save_etags(etags)

    if not frames:
        log.info("Nothing new to ingest. Parquets left untouched.")
        log.info("=" * 70)
        return 0

    raw = pd.concat(frames, ignore_index=True)
    log.info("Combined source rows: %d", len(raw))

    upsert(backfill.DISAGG_FUTOPT_FILE,
           build(raw, "Combined", backfill.DISAGG_FUTOPT_OI_DTYPE), "Disagg FutOpt")
    upsert(backfill.DISAGG_FUT_FILE,
           build(raw, "FutOnly", backfill.DISAGG_FUT_OI_DTYPE), "Disagg Fut")

    log.info("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
