"""
Hardmine — COT CFTC Full History Backfill (CFTC Socrata API)
=============================================================
Direct-from-source counterpart to the LSEG-based sibling project
`LSEG/COT_ALL`, built on the CFTC's own public Socrata API instead of
`lseg.data`. No Workspace/Eikon session and no vendor entitlement required —
the endpoints are public and unauthenticated.

Produces the same three parquet files, with the same column names, order and
dtypes as the LSEG pipeline:

    Database/cot_cit.parquet             CIT / Commodity Index Supplemental
    Database/cot_disagg_futopt.parquet   Disaggregated, futures+options combined
    Database/cot_disagg_fut.parquet      Disaggregated, futures only

plus two more the LSEG project has no counterpart for:

    Database/cot_legacy_futopt.parquet   Legacy, futures+options combined
    Database/cot_legacy_fut.parquet      Legacy, futures only (history to 1986)

Source datasets (publicreporting.cftc.gov):
    kh3c-gbw2   Disaggregated - Combined
    72hh-3qpy   Disaggregated - Futures Only
    4zgm-a668   Commodity Index Trader Supplemental (combined only, by design)
    jun7-fc8e   Legacy - Combined
    6dca-aqww   Legacy - Futures Only

TFF (Traders in Financial Futures, gpe5-46if / yw9f-hn96) is deliberately
skipped — it holds financial contracts only, no commodities.

Differences vs. the LSEG sibling — all in this project's favour:
  - History starts 2006-06-13 (Disagg) / 2006-01-03 (CIT) rather than 2010,
    which is the full published history of both reports.
  - Per-category trader counts (Traders Producer/Swap/MM/Other/Comm/Spec/Index
    Long/Short/Spread) ARE populated. LSEG does not publish these.
  - Concentration ratios (Conc Gross/Net 4/8 Long/Short) ARE populated.
    LSEG does not publish these.
  - The Old/New crop split is real, historical data, so Crop="Old" and
    Crop="Other" rows carry genuine values. LSEG only exposes a live snapshot,
    so its Old/Other rows are zero-filled.

The one thing CFTC does not supply is price:
  - `Px` is NaN. CFTC publishes positions only. Pass --merge-px to backfill it
    from the sibling LSEG/COT_ALL parquets by (Commodity, Date) if that
    project is present and you want chart-ready files.

Coverage is 7 of the sibling's 10 commodities. RC / LCC / LSU (Robusta,
London Cocoa, White Sugar) are ICE Futures Europe contracts and the CFTC does
not report them at all — verified by scanning every cocoa/coffee/sugar
contract in the dataset, not assumed. Use LSEG/COT_ALL for those three.

Usage:
    python cftc_backfill.py                      # full history
    python cftc_backfill.py --start 2015-01-01
    python cftc_backfill.py --merge-px           # pull Px from LSEG/COT_ALL
"""

import argparse
import logging
import os
import sys
import time
from pathlib import Path

import pandas as pd
import requests

LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / "cftc_backfill.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

DB_DIR = Path(__file__).parent.parent / "Database"
CIT_FILE           = DB_DIR / "cot_cit.parquet"
DISAGG_FUT_FILE    = DB_DIR / "cot_disagg_fut.parquet"
DISAGG_FUTOPT_FILE = DB_DIR / "cot_disagg_futopt.parquet"
LEGACY_FUT_FILE    = DB_DIR / "cot_legacy_fut.parquet"
LEGACY_FUTOPT_FILE = DB_DIR / "cot_legacy_futopt.parquet"

# Sibling LSEG project, used only by --merge-px.
LSEG_COT_ALL_DB = Path(__file__).parent.parent.parent / "COT_ALL" / "Database"

# Earlier than any of the reports begin, so each one simply starts wherever
# its own history does: Legacy futures-only 1986, Legacy combined 1995,
# CIT 2006-01, Disaggregated 2006-06.
START_FULL = "1986-01-01"

# ==============================================================================
# API CONFIG
# ==============================================================================
DOMAIN = "https://publicreporting.cftc.gov/resource"
DATASET_DISAGG_FUTOPT = "kh3c-gbw2"
DATASET_DISAGG_FUT    = "72hh-3qpy"
DATASET_CIT           = "4zgm-a668"
DATASET_LEGACY_FUTOPT = "jun7-fc8e"
DATASET_LEGACY_FUT    = "6dca-aqww"
# TFF (gpe5-46if / yw9f-hn96) is deliberately not ingested: it covers
# financial futures only — rates, equity indices, FX — with no commodity
# contracts at all. Revisit only if the desk wants BRL / Dollar Index
# positioning alongside the softs.

PAGE = 50_000          # Socrata caps a single page well above our row counts
TIMEOUT = 180
RETRIES = 4

# ==============================================================================
# COMMODITY CONFIG
# ==============================================================================
# Keyed by the sibling project's commodity code so the two datasets stack.
# The value is the CFTC contract market code, which is stable across the
# exchange rename from NEW YORK BOARD OF TRADE to ICE FUTURES U.S. in Sept
# 2007 and across the COPPER-GRADE #1 -> COPPER- #1 contract rename in Feb
# 2022, so filtering on it (never on the market name) keeps history continuous.
DISAGG_COMMODITIES = {
    "KC": "083731",   # Coffee C      - ICE Futures U.S.
    "CC": "073732",   # Cocoa         - ICE Futures U.S.
    "SB": "080732",   # Sugar No. 11  - ICE Futures U.S.
    "CT": "033661",   # Cotton No. 2  - ICE Futures U.S.
    "GC": "088691",   # Gold          - COMEX
    "SI": "084691",   # Silver        - COMEX
    "HG": "085692",   # Copper #1     - COMEX
}

# CIT is CFTC's ag-only Commodity Index Supplemental report, so the metals are
# absent by design — the same situation RC/LCC/LSU are in on the LSEG side,
# which the dashboard's CIT_COMMS gating already handles.
CIT_COMMODITIES = {k: v for k, v in DISAGG_COMMODITIES.items()
                   if k in ("KC", "CC", "SB", "CT")}

# ICE Futures Europe softs, present in LSEG/COT_ALL but not obtainable here.
NOT_ON_CFTC = ("RC", "LCC", "LSU")

# The Legacy report covers every CFTC market, so it is the only place the
# grain complex shows up. Globex-style codes are used rather than the CBOT
# floor letters (C, W, S) because those would collide with the ICE London
# softs codes if RC/LCC/LSU are ever added from ICE's own feed.
GRAIN_COMMODITIES = {
    "ZC": "002602",   # Corn         - CBOT
    "ZW": "001602",   # Wheat SRW    - CBOT  (named WHEAT-SRW from Dec 2013)
    "KW": "001612",   # Wheat HRW    - KCBT, later CBOT
    "ZS": "005602",   # Soybeans     - CBOT
    "ZM": "026603",   # Soybean Meal - CBOT
    "ZL": "007601",   # Soybean Oil  - CBOT
}
LEGACY_COMMODITIES = {**DISAGG_COMMODITIES, **GRAIN_COMMODITIES}

# ==============================================================================
# FIELD MAPS  (target column -> CFTC API field)
# ==============================================================================
# CFTC's per-crop suffixes are irregular (_all / _old / _other / _1 / _2, plus
# a few fields with a doubled underscore), so each crop is spelled out rather
# than derived. Pct OI columns are deliberately absent from these maps: CFTC
# publishes them rounded to 1dp, so they are recomputed from positions/OI
# below at full precision, which is what the LSEG sibling does too.

DISAGG_POS = {
    "All": {
        "Total OI":       "open_interest_all",
        "Producer Long":  "prod_merc_positions_long",
        "Producer Short": "prod_merc_positions_short",
        "Swap Long":      "swap_positions_long_all",
        "Swap Short":     "swap__positions_short_all",
        "Swap Spread":    "swap__positions_spread_all",
        "MM Long":        "m_money_positions_long_all",
        "MM Short":       "m_money_positions_short_all",
        "MM Spread":      "m_money_positions_spread",
        "Other Long":     "other_rept_positions_long",
        "Other Short":    "other_rept_positions_short",
        "Other Spread":   "other_rept_positions_spread",
        "Tot Rept Long":  "tot_rept_positions_long_all",
        "Tot Rept Short": "tot_rept_positions_short",
        "Non Rep Long":   "nonrept_positions_long_all",
        "Non Rep Short":  "nonrept_positions_short_all",
    },
    "Old": {
        "Total OI":       "open_interest_old",
        "Producer Long":  "prod_merc_positions_long_1",
        "Producer Short": "prod_merc_positions_short_1",
        "Swap Long":      "swap_positions_long_old",
        "Swap Short":     "swap__positions_short_old",
        "Swap Spread":    "swap__positions_spread_old",
        "MM Long":        "m_money_positions_long_old",
        "MM Short":       "m_money_positions_short_old",
        "MM Spread":      "m_money_positions_spread_1",
        "Other Long":     "other_rept_positions_long_1",
        "Other Short":    "other_rept_positions_short_1",
        "Other Spread":   "other_rept_positions_spread_1",
        "Tot Rept Long":  "tot_rept_positions_long_old",
        "Tot Rept Short": "tot_rept_positions_short_1",
        "Non Rep Long":   "nonrept_positions_long_old",
        "Non Rep Short":  "nonrept_positions_short_old",
    },
    "Other": {
        "Total OI":       "open_interest_other",
        "Producer Long":  "prod_merc_positions_long_2",
        "Producer Short": "prod_merc_positions_short_2",
        "Swap Long":      "swap_positions_long_other",
        "Swap Short":     "swap__positions_short_other",
        "Swap Spread":    "swap__positions_spread_other",
        "MM Long":        "m_money_positions_long_other",
        "MM Short":       "m_money_positions_short_other",
        "MM Spread":      "m_money_positions_spread_2",
        "Other Long":     "other_rept_positions_long_2",
        "Other Short":    "other_rept_positions_short_2",
        "Other Spread":   "other_rept_positions_spread_2",
        "Tot Rept Long":  "tot_rept_positions_long_other",
        "Tot Rept Short": "tot_rept_positions_short_2",
        "Non Rep Long":   "nonrept_positions_long_other",
        "Non Rep Short":  "nonrept_positions_short_other",
    },
}

DISAGG_TRADERS = {
    "All": {
        "Traders Total":          "traders_tot_all",
        "Traders Producer Long":  "traders_prod_merc_long_all",
        "Traders Producer Short": "traders_prod_merc_short_all",
        "Traders Swap Long":      "traders_swap_long_all",
        "Traders Swap Short":     "traders_swap_short_all",
        "Traders Swap Spread":    "traders_swap_spread_all",
        "Traders MM Long":        "traders_m_money_long_all",
        "Traders MM Short":       "traders_m_money_short_all",
        "Traders MM Spread":      "traders_m_money_spread_all",
        "Traders Other Long":     "traders_other_rept_long_all",
        "Traders Other Short":    "traders_other_rept_short",
        "Traders Other Spread":   "traders_other_rept_spread",
        "Traders Tot Rept Long":  "traders_tot_rept_long_all",
        "Traders Tot Rept Short": "traders_tot_rept_short_all",
    },
    "Old": {
        "Traders Total":          "traders_tot_old",
        "Traders Producer Long":  "traders_prod_merc_long_old",
        "Traders Producer Short": "traders_prod_merc_short_old",
        "Traders Swap Long":      "traders_swap_long_old",
        "Traders Swap Short":     "traders_swap_short_old",
        "Traders Swap Spread":    "traders_swap_spread_old",
        "Traders MM Long":        "traders_m_money_long_old",
        "Traders MM Short":       "traders_m_money_short_old",
        "Traders MM Spread":      "traders_m_money_spread_old",
        "Traders Other Long":     "traders_other_rept_long_old",
        "Traders Other Short":    "traders_other_rept_short_1",
        "Traders Other Spread":   "traders_other_rept_spread_1",
        "Traders Tot Rept Long":  "traders_tot_rept_long_old",
        "Traders Tot Rept Short": "traders_tot_rept_short_old",
    },
    "Other": {
        "Traders Total":          "traders_tot_other",
        "Traders Producer Long":  "traders_prod_merc_long_other",
        "Traders Producer Short": "traders_prod_merc_short_other",
        "Traders Swap Long":      "traders_swap_long_other",
        "Traders Swap Short":     "traders_swap_short_other",
        "Traders Swap Spread":    "traders_swap_spread_other",
        "Traders MM Long":        "traders_m_money_long_other",
        "Traders MM Short":       "traders_m_money_short_other",
        "Traders MM Spread":      "traders_m_money_spread_other",
        "Traders Other Long":     "traders_other_rept_long_other",
        "Traders Other Short":    "traders_other_rept_short_2",
        "Traders Other Spread":   "traders_other_rept_spread_2",
        "Traders Tot Rept Long":  "traders_tot_rept_long_other",
        "Traders Tot Rept Short": "traders_tot_rept_short_other",
    },
}

DISAGG_CONC = {
    "All": {
        "Conc Gross 4 Long":  "conc_gross_le_4_tdr_long",
        "Conc Gross 4 Short": "conc_gross_le_4_tdr_short",
        "Conc Gross 8 Long":  "conc_gross_le_8_tdr_long",
        "Conc Gross 8 Short": "conc_gross_le_8_tdr_short",
        "Conc Net 4 Long":    "conc_net_le_4_tdr_long_all",
        "Conc Net 4 Short":   "conc_net_le_4_tdr_short_all",
        "Conc Net 8 Long":    "conc_net_le_8_tdr_long_all",
        "Conc Net 8 Short":   "conc_net_le_8_tdr_short_all",
    },
    "Old": {
        "Conc Gross 4 Long":  "conc_gross_le_4_tdr_long_1",
        "Conc Gross 4 Short": "conc_gross_le_4_tdr_short_1",
        "Conc Gross 8 Long":  "conc_gross_le_8_tdr_long_1",
        "Conc Gross 8 Short": "conc_gross_le_8_tdr_short_1",
        "Conc Net 4 Long":    "conc_net_le_4_tdr_long_old",
        "Conc Net 4 Short":   "conc_net_le_4_tdr_short_old",
        "Conc Net 8 Long":    "conc_net_le_8_tdr_long_old",
        "Conc Net 8 Short":   "conc_net_le_8_tdr_short_old",
    },
    "Other": {
        "Conc Gross 4 Long":  "conc_gross_le_4_tdr_long_2",
        "Conc Gross 4 Short": "conc_gross_le_4_tdr_short_2",
        "Conc Gross 8 Long":  "conc_gross_le_8_tdr_long_2",
        "Conc Gross 8 Short": "conc_gross_le_8_tdr_short_2",
        "Conc Net 4 Long":    "conc_net_le_4_tdr_long_other",
        "Conc Net 4 Short":   "conc_net_le_4_tdr_short_other",
        "Conc Net 8 Long":    "conc_net_le_8_tdr_long_other",
        "Conc Net 8 Short":   "conc_net_le_8_tdr_short_other",
    },
}

# ── Legacy ────────────────────────────────────────────────────────────────
# The original COT format: three trader classes instead of the Disaggregated
# four-plus. NonComm ≈ MM + Other Reportables, Comm ≈ Producer/Merchant +
# Swap Dealers. Coarser, but published back to 1986 for the futures-only
# report, which is 20 years deeper than Disaggregated goes.
# Note the two typos in CFTC's own field names, reproduced exactly:
# "noncomm_postions_spread_all" and "traders_noncomm_spead_old".
LEGACY_POS = {
    "All": {
        "Total OI":       "open_interest_all",
        "NonComm Long":   "noncomm_positions_long_all",
        "NonComm Short":  "noncomm_positions_short_all",
        "NonComm Spread": "noncomm_postions_spread_all",
        "Comm Long":      "comm_positions_long_all",
        "Comm Short":     "comm_positions_short_all",
        "Tot Rept Long":  "tot_rept_positions_long_all",
        "Tot Rept Short": "tot_rept_positions_short",
        "Non Rep Long":   "nonrept_positions_long_all",
        "Non Rep Short":  "nonrept_positions_short_all",
    },
    "Old": {
        "Total OI":       "open_interest_old",
        "NonComm Long":   "noncomm_positions_long_old",
        "NonComm Short":  "noncomm_positions_short_old",
        "NonComm Spread": "noncomm_positions_spread",
        "Comm Long":      "comm_positions_long_old",
        "Comm Short":     "comm_positions_short_old",
        "Tot Rept Long":  "tot_rept_positions_long_old",
        "Tot Rept Short": "tot_rept_positions_short_1",
        "Non Rep Long":   "nonrept_positions_long_old",
        "Non Rep Short":  "nonrept_positions_short_old",
    },
    "Other": {
        "Total OI":       "open_interest_other",
        "NonComm Long":   "noncomm_positions_long_other",
        "NonComm Short":  "noncomm_positions_short_other",
        "NonComm Spread": "noncomm_positions_spread_1",
        "Comm Long":      "comm_positions_long_other",
        "Comm Short":     "comm_positions_short_other",
        "Tot Rept Long":  "tot_rept_positions_long_other",
        "Tot Rept Short": "tot_rept_positions_short_2",
        "Non Rep Long":   "nonrept_positions_long_other",
        "Non Rep Short":  "nonrept_positions_short_other",
    },
}

LEGACY_TRADERS = {
    "All": {
        "Traders Total":          "traders_tot_all",
        "Traders NonComm Long":   "traders_noncomm_long_all",
        "Traders NonComm Short":  "traders_noncomm_short_all",
        "Traders NonComm Spread": "traders_noncomm_spread_all",
        "Traders Comm Long":      "traders_comm_long_all",
        "Traders Comm Short":     "traders_comm_short_all",
        "Traders Tot Rept Long":  "traders_tot_rept_long_all",
        "Traders Tot Rept Short": "traders_tot_rept_short_all",
    },
    "Old": {
        "Traders Total":          "traders_tot_old",
        "Traders NonComm Long":   "traders_noncomm_long_old",
        "Traders NonComm Short":  "traders_noncomm_short_old",
        "Traders NonComm Spread": "traders_noncomm_spead_old",
        "Traders Comm Long":      "traders_comm_long_old",
        "Traders Comm Short":     "traders_comm_short_old",
        "Traders Tot Rept Long":  "traders_tot_rept_long_old",
        "Traders Tot Rept Short": "traders_tot_rept_short_old",
    },
    "Other": {
        "Traders Total":          "traders_tot_other",
        "Traders NonComm Long":   "traders_noncomm_long_other",
        "Traders NonComm Short":  "traders_noncomm_short_other",
        "Traders NonComm Spread": "traders_noncomm_spread_other",
        "Traders Comm Long":      "traders_comm_long_other",
        "Traders Comm Short":     "traders_comm_short_other",
        "Traders Tot Rept Long":  "traders_tot_rept_long_other",
        "Traders Tot Rept Short": "traders_tot_rept_short_other",
    },
}

# Concentration field names are shared with the Disaggregated report.
LEGACY_CONC = DISAGG_CONC

# CIT/Supplemental is combined-only and has no crop split, so one flat map.
# The "NoCIT" fields are the commercial / non-commercial splits with index
# traders already stripped out, which is what the sibling's Comm/Spec columns
# hold. Field names in this dataset are mixed-case and case-sensitive.
CIT_POS = {
    "Comm Long":     "comm_positions_long_all_nocit",
    "Comm Short":    "Comm_Positions_Short_All_NoCIT",
    "Spec Long":     "NComm_Postions_Long_All_NoCIT",
    "Spec Short":    "NComm_Postions_Short_All_NoCIT",
    "Spec Spread":   "NComm_Postions_Spread_All_NoCIT",
    "Index Long":    "cit_positions_long_all",
    "Index Short":   "cit_positions_short_all",
    "Non Rep Long":  "nonrept_positions_long_all",
    "Non Rep Short": "nonrept_positions_short_all",
    "Total OI":      "open_interest_all",
}
CIT_TRADERS = {
    "Traders Comm Long":      "traders_comm_long_all_nocit",
    "Traders Comm Short":     "traders_comm_short_all_nocit",
    "Traders Spec Long":      "Traders_NonComm_Long_All_NoCIT",
    "Traders Spec Short":     "Traders_NonComm_Short_All_NoCIT",
    "Traders Spec Spread":    "Traders_NonComm_Spread_All_NoCIT",
    "Traders Index Long":     "traders_cit_long_all",
    "Traders Index Short":    "traders_cit_short_all",
    "Traders Tot Rept Long":  "Traders_Tot_Rept_Long_All_NoCIT",
    "Traders Tot Rept Short": "Traders_Tot_Rept_Short_All_NoCIT",
}

# ==============================================================================
# OUTPUT SCHEMA  (column order and dtypes copied from LSEG/COT_ALL)
# ==============================================================================
DISAGG_POS_COLS = [
    "Producer Long", "Producer Short",
    "Swap Long", "Swap Short", "Swap Spread",
    "MM Long", "MM Short", "MM Spread",
    "Other Long", "Other Short", "Other Spread",
    "Tot Rept Long", "Tot Rept Short", "Non Rep Long", "Non Rep Short",
]
DISAGG_TRADER_CAT_COLS = [
    "Traders Producer Long", "Traders Producer Short",
    "Traders Swap Long", "Traders Swap Short", "Traders Swap Spread",
    "Traders MM Long", "Traders MM Short", "Traders MM Spread",
    "Traders Other Long", "Traders Other Short", "Traders Other Spread",
]
DISAGG_CONC_COLS = [
    "Conc Gross 4 Long", "Conc Gross 4 Short",
    "Conc Gross 8 Long", "Conc Gross 8 Short",
    "Conc Net 4 Long", "Conc Net 4 Short",
    "Conc Net 8 Long", "Conc Net 8 Short",
]
DISAGG_FINAL_COLS = (
    ["Commodity", "Crop", "Date", "Total OI"]
    + DISAGG_POS_COLS
    + ["Traders Total"] + DISAGG_TRADER_CAT_COLS
    + ["Traders Tot Rept Long", "Traders Tot Rept Short"]
    + DISAGG_CONC_COLS
    + ["Pct OI " + c for c in DISAGG_POS_COLS]
    + ["Px"]
)

LEGACY_POS_COLS = [
    "NonComm Long", "NonComm Short", "NonComm Spread",
    "Comm Long", "Comm Short",
    "Tot Rept Long", "Tot Rept Short", "Non Rep Long", "Non Rep Short",
]
LEGACY_TRADER_CAT_COLS = [
    "Traders NonComm Long", "Traders NonComm Short", "Traders NonComm Spread",
    "Traders Comm Long", "Traders Comm Short",
]
LEGACY_FINAL_COLS = (
    ["Commodity", "Crop", "Date", "Total OI"]
    + LEGACY_POS_COLS
    + ["Traders Total"] + LEGACY_TRADER_CAT_COLS
    + ["Traders Tot Rept Long", "Traders Tot Rept Short"]
    + DISAGG_CONC_COLS
    + ["Pct OI " + c for c in LEGACY_POS_COLS]
    + ["Px"]
)

CIT_POS_COLS = [
    "Comm Long", "Comm Short", "Spec Long", "Spec Short", "Spec Spread",
    "Index Long", "Index Short", "Non Rep Long", "Non Rep Short",
]
CIT_TRADER_CAT_COLS = [
    "Traders Comm Long", "Traders Comm Short",
    "Traders Spec Long", "Traders Spec Short", "Traders Spec Spread",
    "Traders Index Long", "Traders Index Short",
]
CIT_FINAL_COLS = (
    ["Commodity", "Date"] + CIT_POS_COLS + ["Total OI"]
    + CIT_TRADER_CAT_COLS
    + ["Traders Tot Rept Long", "Traders Tot Rept Short"]
    + ["Pct OI " + c for c in CIT_POS_COLS]
    + ["Px"]
)

# The sibling stores Total OI as Float64 in cot_disagg_futopt.parquet but
# Int64 in the other two. Reproduced verbatim so a consumer reading both
# projects sees identical schemas rather than a dtype clash on concat.
DISAGG_FUTOPT_OI_DTYPE = "Float64"
DISAGG_FUT_OI_DTYPE    = "Int64"
# Legacy has no LSEG counterpart to mirror, so it just uses the sane type.
LEGACY_OI_DTYPE        = "Int64"


# ==============================================================================
# FETCH
# ==============================================================================
def _session() -> requests.Session:
    """A token is optional at this volume but lifts the throttling limits.
    Set CFTC_APP_TOKEN in the environment if the desk ever starts hitting 429s."""
    s = requests.Session()
    token = os.environ.get("CFTC_APP_TOKEN")
    if token:
        s.headers["X-App-Token"] = token
    return s


def fetch_dataset(dataset: str, codes: list, start: str,
                  session: requests.Session = None) -> pd.DataFrame:
    """Pull every row for the given contract market codes from `start` onward.

    Filtering happens server-side on cftc_contract_market_code, so this moves a
    few thousand rows rather than the ~190k-row full dataset.
    """
    session = session or _session()
    code_list = ", ".join("'%s'" % c for c in codes)
    where = ("cftc_contract_market_code in (%s) "
             "and report_date_as_yyyy_mm_dd >= '%sT00:00:00.000'" % (code_list, start))

    frames, offset = [], 0
    while True:
        params = {
            "$limit": PAGE,
            "$offset": offset,
            "$where": where,
            "$order": "report_date_as_yyyy_mm_dd ASC, cftc_contract_market_code ASC",
        }
        for attempt in range(RETRIES):
            try:
                r = session.get("%s/%s.json" % (DOMAIN, dataset), params=params,
                                timeout=TIMEOUT)
                r.raise_for_status()
                break
            except Exception as exc:
                if attempt == RETRIES - 1:
                    raise
                log.warning("  retry %d/%d for %s — %s", attempt + 1, RETRIES - 1,
                            dataset, str(exc)[:120])
                time.sleep(5 * (attempt + 1))

        rows = r.json()
        if not rows:
            break
        frames.append(pd.DataFrame.from_records(rows))
        offset += len(rows)
        if len(rows) < PAGE:
            break

    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    log.info("  %s: %d source rows", dataset, len(df))
    return df


# ==============================================================================
# TRANSFORM
# ==============================================================================
def _num(df: pd.DataFrame, field: str) -> pd.Series:
    """Numeric view of a CFTC field, tolerant of it being absent from a
    particular vintage of the API response (older weeks omit empty fields)."""
    if field not in df.columns:
        return pd.Series(pd.NA, index=df.index, dtype="Float64")
    return pd.to_numeric(df[field], errors="coerce").astype("Float64")


def _add_pct(out: pd.DataFrame, pos_cols: list) -> None:
    """Recompute Pct OI at full precision. CFTC publishes its own pct_of_oi_*
    fields rounded to 1dp; the LSEG sibling computes them, so we do too, which
    keeps the two projects' percentage columns directly comparable."""
    oi = out["Total OI"].astype("Float64")
    denom = oi.where(oi > 0)          # Old/Other OI is 0 for non-crop-year contracts
    for c in pos_cols:
        out["Pct OI " + c] = (out[c].astype("Float64") / denom * 100).astype("Float64")


def _build_crop_report(raw: pd.DataFrame, code_to_comm: dict, oi_dtype: str,
                       pos_map: dict, traders_map: dict, conc_map: dict,
                       pos_cols: list, trader_cat_cols: list,
                       final_cols: list) -> pd.DataFrame:
    """Reshape any of the crop-split reports (Disaggregated or Legacy) into the
    long format: one row per (Commodity, Crop, Date), Crop in All/Old/Other.

    The two reports differ only in their field maps and column lists, so they
    share this body rather than each carrying a near-identical copy."""
    if raw.empty:
        return pd.DataFrame(columns=final_cols)

    date = pd.to_datetime(raw["report_date_as_yyyy_mm_dd"], errors="coerce").dt.normalize()
    commodity = raw["cftc_contract_market_code"].map(code_to_comm)

    blocks = []
    for crop in ("All", "Old", "Other"):
        out = pd.DataFrame({"Commodity": commodity, "Crop": crop, "Date": date})
        for mapping in (pos_map[crop], traders_map[crop], conc_map[crop]):
            for col, field in mapping.items():
                out[col] = _num(raw, field)
        _add_pct(out, pos_cols)
        out["Px"] = pd.Series(pd.NA, index=out.index, dtype="Float64")
        blocks.append(out)

    df = pd.concat(blocks, ignore_index=True)
    df = df.dropna(subset=["Commodity", "Date"])
    # CFTC revises prior weeks in place; a later row for the same key wins.
    df = df.drop_duplicates(subset=["Commodity", "Crop", "Date"], keep="last")
    df = df[final_cols]

    df["Total OI"] = df["Total OI"].round().astype(oi_dtype)
    for c in pos_cols + ["Traders Total",
                         "Traders Tot Rept Long", "Traders Tot Rept Short"]:
        df[c] = df[c].round().astype("Int64")
    for c in trader_cat_cols + DISAGG_CONC_COLS:
        df[c] = df[c].astype("float64")

    return df.sort_values(["Commodity", "Crop", "Date"]).reset_index(drop=True)


def build_disagg(raw: pd.DataFrame, code_to_comm: dict, oi_dtype: str) -> pd.DataFrame:
    """Disaggregated report — Producer/Merchant, Swap, Managed Money, Other."""
    return _build_crop_report(
        raw, code_to_comm, oi_dtype,
        DISAGG_POS, DISAGG_TRADERS, DISAGG_CONC,
        DISAGG_POS_COLS, DISAGG_TRADER_CAT_COLS, DISAGG_FINAL_COLS)


def build_legacy(raw: pd.DataFrame, code_to_comm: dict,
                 oi_dtype: str = LEGACY_OI_DTYPE) -> pd.DataFrame:
    """Legacy report — Non-Commercial, Commercial, Non-Reportable."""
    return _build_crop_report(
        raw, code_to_comm, oi_dtype,
        LEGACY_POS, LEGACY_TRADERS, LEGACY_CONC,
        LEGACY_POS_COLS, LEGACY_TRADER_CAT_COLS, LEGACY_FINAL_COLS)


def build_cit(raw: pd.DataFrame, code_to_comm: dict) -> pd.DataFrame:
    """Reshape the CIT/Supplemental dataset. No crop split in this report."""
    if raw.empty:
        return pd.DataFrame(columns=CIT_FINAL_COLS)

    out = pd.DataFrame({
        "Commodity": raw["cftc_contract_market_code"].map(code_to_comm),
        "Date": pd.to_datetime(raw["report_date_as_yyyy_mm_dd"],
                               errors="coerce").dt.normalize(),
    })
    for mapping in (CIT_POS, CIT_TRADERS):
        for col, field in mapping.items():
            out[col] = _num(raw, field)

    _add_pct(out, CIT_POS_COLS)
    out["Px"] = pd.Series(pd.NA, index=out.index, dtype="Float64")

    out = out.dropna(subset=["Commodity", "Date"])
    out = out.drop_duplicates(subset=["Commodity", "Date"], keep="last")
    out = out[CIT_FINAL_COLS]

    for c in CIT_POS_COLS + ["Total OI", "Traders Tot Rept Long",
                             "Traders Tot Rept Short"]:
        out[c] = out[c].round().astype("Int64")
    for c in CIT_TRADER_CAT_COLS:
        out[c] = out[c].astype("float64")

    return out.sort_values(["Commodity", "Date"]).reset_index(drop=True)


# ==============================================================================
# OPTIONAL PRICE MERGE
# ==============================================================================
def merge_px(df: pd.DataFrame, source_name: str) -> pd.DataFrame:
    """Fill Px from the sibling LSEG/COT_ALL parquet of the same name, matched
    on (Commodity, Date). Purely cosmetic — no position data is touched — and
    skipped with a warning if that project isn't checked out alongside this one."""
    src = LSEG_COT_ALL_DB / source_name
    if not src.exists():
        log.warning("  --merge-px: %s not found, leaving Px as NaN", src)
        return df
    ref = pd.read_parquet(src, columns=["Commodity", "Date", "Px"])
    ref = ref.drop_duplicates(subset=["Commodity", "Date"], keep="last")
    cols = df.columns.tolist()
    merged = df.drop(columns=["Px"]).merge(ref, on=["Commodity", "Date"], how="left")
    merged["Px"] = merged["Px"].astype("Float64")
    log.info("  --merge-px: filled %d/%d rows from %s",
             int(merged["Px"].notna().sum()), len(merged), source_name)
    return merged[cols]


# ==============================================================================
# MAIN
# ==============================================================================
def write_and_report(name: str, df: pd.DataFrame, path: Path,
                     preserve: tuple = ()) -> bool:
    """Write one parquet. `preserve` names commodities this backfill does not
    produce but which may already be in the file — the London softs written by
    ice_ingest.py. Without this, a full CFTC rebuild would silently delete
    them, since RC/LCC/LSU never appear in any CFTC dataset."""
    if df.empty:
        log.error("%s came back empty — not writing %s", name, path.name)
        return False

    if preserve and path.exists():
        existing = pd.read_parquet(path)
        keep = existing[existing["Commodity"].isin(preserve)]
        if not keep.empty:
            df = pd.concat([df, keep], ignore_index=True)
            df = df.sort_values(["Commodity", "Crop", "Date"]).reset_index(drop=True)
            log.info("  kept %d non-CFTC rows (%s) already in %s",
                     len(keep), ", ".join(sorted(keep["Commodity"].unique())),
                     path.name)

    df.to_parquet(path, engine="pyarrow", index=False)
    log.info("%-14s -> %-28s rows=%-7d cols=%d  %s -> %s  [%s]",
             name, path.name, len(df), len(df.columns),
             df["Date"].min().date(), df["Date"].max().date(),
             ",".join(sorted(df["Commodity"].unique())))
    return True


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Backfill the COT parquets straight from the CFTC API.")
    ap.add_argument("--start", default=START_FULL,
                    help="earliest report date to pull (YYYY-MM-DD)")
    ap.add_argument("--merge-px", action="store_true",
                    help="fill Px from the sibling LSEG/COT_ALL parquets")
    args = ap.parse_args()

    DB_DIR.mkdir(parents=True, exist_ok=True)
    session = _session()

    disagg_codes = list(DISAGG_COMMODITIES.values())
    cit_codes = list(CIT_COMMODITIES.values())
    disagg_lookup = {v: k for k, v in DISAGG_COMMODITIES.items()}
    cit_lookup = {v: k for k, v in CIT_COMMODITIES.items()}

    log.info("CFTC COT backfill from %s", args.start)
    log.info("Disagg/CIT commodities: %s   (not published by CFTC: %s)",
             ", ".join(DISAGG_COMMODITIES), ", ".join(NOT_ON_CFTC))
    log.info("Legacy commodities:     %s", ", ".join(LEGACY_COMMODITIES))

    log.info("Fetching Disaggregated - Combined ...")
    futopt = build_disagg(
        fetch_dataset(DATASET_DISAGG_FUTOPT, disagg_codes, args.start, session),
        disagg_lookup, DISAGG_FUTOPT_OI_DTYPE)

    log.info("Fetching Disaggregated - Futures Only ...")
    fut = build_disagg(
        fetch_dataset(DATASET_DISAGG_FUT, disagg_codes, args.start, session),
        disagg_lookup, DISAGG_FUT_OI_DTYPE)

    log.info("Fetching CIT / Supplemental ...")
    cit = build_cit(
        fetch_dataset(DATASET_CIT, cit_codes, args.start, session), cit_lookup)

    legacy_codes = list(LEGACY_COMMODITIES.values())
    legacy_lookup = {v: k for k, v in LEGACY_COMMODITIES.items()}

    log.info("Fetching Legacy - Combined ...")
    legacy_futopt = build_legacy(
        fetch_dataset(DATASET_LEGACY_FUTOPT, legacy_codes, args.start, session),
        legacy_lookup)

    log.info("Fetching Legacy - Futures Only ...")
    legacy_fut = build_legacy(
        fetch_dataset(DATASET_LEGACY_FUT, legacy_codes, args.start, session),
        legacy_lookup)

    if args.merge_px:
        futopt = merge_px(futopt, "cot_disagg_futopt.parquet")
        fut = merge_px(fut, "cot_disagg_fut.parquet")
        cit = merge_px(cit, "cot_cit.parquet")

    ok = True
    ok &= write_and_report("Disagg FutOpt", futopt, DISAGG_FUTOPT_FILE,
                           preserve=NOT_ON_CFTC)
    ok &= write_and_report("Disagg Fut", fut, DISAGG_FUT_FILE,
                           preserve=NOT_ON_CFTC)
    ok &= write_and_report("CIT", cit, CIT_FILE)
    ok &= write_and_report("Legacy FutOpt", legacy_futopt, LEGACY_FUTOPT_FILE)
    ok &= write_and_report("Legacy Fut", legacy_fut, LEGACY_FUT_FILE)

    log.info("Done." if ok else "Finished with errors — see above.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
