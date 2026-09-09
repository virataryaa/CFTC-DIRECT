# CFTC — COT direct from the CFTC public API

Schema-compatible twin of the sibling `LSEG/COT_ALL` project, sourced from the
**CFTC's own public Socrata API** instead of `lseg.data`. No LSEG Workspace or
Eikon session, no vendor entitlement, no desktop app that has to be open — the
endpoints are public and unauthenticated.

The three Disagg/CIT parquet files carry **identical column names, column
order and dtypes** to their `COT_ALL` counterparts, verified programmatically,
so any consumer of one reads the other unchanged. Two further Legacy files go
beyond what the LSEG project covers at all.

## What's here

- **`Code/`** — `cftc_backfill.py` (full-history builder), `cftc_ingest.py`
  (weekly incremental) and `ice_ingest.py` (the London softs from ICE). The
  latter two import the backfill module's config, schema and reshape logic —
  nothing is duplicated.
- **`Automator/`** — `run.bat`, which runs `cftc_ingest` then `ice_ingest` and
  appends to `run_log.txt`. Not yet registered with Task Scheduler.
- **`Database/`** — `cot_cit.parquet`, `cot_disagg_futopt.parquet`,
  `cot_disagg_fut.parquet`, `cot_legacy_futopt.parquet`,
  `cot_legacy_fut.parquet`.
- **`Dashboard/`** — deliberately empty for now.

## Source datasets

| File | CFTC dataset | Report |
|---|---|---|
| `cot_disagg_futopt.parquet` | `kh3c-gbw2` | Disaggregated — Combined (futures + options) |
| `cot_disagg_fut.parquet` | `72hh-3qpy` | Disaggregated — Futures Only |
| `cot_cit.parquet` | `4zgm-a668` | Commodity Index Trader Supplemental |
| `cot_legacy_futopt.parquet` | `jun7-fc8e` | Legacy — Combined |
| `cot_legacy_fut.parquet` | `6dca-aqww` | Legacy — Futures Only |

**TFF is deliberately not ingested.** The two Traders in Financial Futures
datasets (`gpe5-46if`, `yw9f-hn96`) hold financial contracts only — rates,
equity indices, FX — with no commodity contracts at all. They do carry
Brazilian Real, US Dollar Index and Euro FX, so they are worth revisiting if
the desk ever wants macro positioning alongside the softs.

## Coverage

| File | Commodities | Rows | History |
|---|---|---|---|
| Disagg futopt / fut | KC CC SB CT GC SI HG | 22,176 each | 2006-06-13 → 2026-09-01 |
| CIT | KC CC SB CT | 4,316 | 2006-01-03 → 2026-09-01 |
| Legacy futopt | the 7 + ZC ZW KW ZS ZM ZL | 62,253 | 1995-03-21 → 2026-09-01 |
| Legacy fut | the 7 + ZC ZW KW ZS ZM ZL | 69,846 | **1986-01-15** → 2026-09-01 |

The Legacy report covers every CFTC market, so it is the only one of the three
that can carry the grain complex: `ZC` corn, `ZW` Chicago wheat, `KW` KC
wheat, `ZS` soybeans, `ZM` soymeal, `ZL` soyoil. Globex-style codes are used
rather than the CBOT floor letters (C, W, S) so they cannot collide with the
ICE London softs codes if `RC`/`LCC`/`LSU` are ever added from ICE's own feed.
Grain history is shorter than the softs': corn, both wheats and soybeans start
1998-01-06, while soymeal and soyoil go back to 1986 with the rest.

Commodities are filtered on **CFTC contract market code**, never on market
name, so history stays continuous across the NEW YORK BOARD OF TRADE → ICE
FUTURES U.S. rename (Sept 2007) and the COPPER-GRADE #1 → COPPER- #1 rename
(Feb 2022).

**`RC` / `LCC` / `LSU` come from ICE, not the CFTC.** Robusta, London Cocoa
and White Sugar are ICE Futures Europe contracts, so the CFTC has no
reporting authority over them and they appear in none of its datasets —
confirmed by scanning every cocoa/coffee/sugar contract in the data, not
assumed. `ice_ingest.py` fills the gap from ICE's own free weekly file, and
writes them into the same two disagg parquets, so all ten commodities now sit
in one place with no LSEG dependency at all. See "The London softs" below.

## How this compares to LSEG/COT_ALL

Verified by merging both datasets on `(Commodity, Crop, Date)` over the 6,090
overlapping `Crop="All"` disagg rows and all 3,480 overlapping CIT rows:

**Every position, open-interest and Pct OI column matches the LSEG values
exactly — max absolute difference 0.0.** Incidentally, this also settles the
open question in the `COT_ALL` README about 2012/2013/2015/2018 weeks where
LSEG disagreed with the archived ICE snapshot: CFTC agrees with LSEG, so those
were CFTC revisions and ICE's archive was the stale side.

Every gap the `COT_ALL` README lists is either filled here, or turns out not
to be a gap at all:

| | LSEG/COT_ALL | CFTC (this project) |
|---|---|---|
| History start | 2010-01-05 | 2006-06-13 (2006-01-03 CIT) — the full published history |
| Per-category trader counts | not published by LSEG, all NaN | **populated** (100% of rows) |
| Concentration ratios (Conc Gross/Net 4/8) | not published by LSEG, all NaN | **populated** (100% of rows) |
| Old/New crop split | present and correct — see note below | matches, to within ±4 lots |
| `Px` | populated from LSEG price RICs | NaN — see below |

### Two intentional differences to be aware of

1. **`Px` is NaN.** The CFTC publishes positions only; there is no price in
   any of these datasets. Run either script with `--merge-px` to fill it from
   the sibling `LSEG/COT_ALL` parquets on `(Commodity, Date)` if you want
   chart-ready files. That merge touches nothing but the `Px` column.

2. **`Traders Tot Rept Long` / `Short` differ from LSEG in every row**, and
   this project's numbers are the correct ones. LSEG cannot publish the
   figure, so `COT_ALL` derives it as the sum of the four category counts
   (Producer + Swap + MM + Other). CFTC publishes the actual distinct count of
   reportable traders on each side, which is larger because it also captures
   traders whose position sits in the spread buckets. For KC on 2026-09-01:
   CFTC 279 long vs LSEG's derived 201. `Traders Total` is unaffected and
   matches LSEG exactly.

### On the Old/New crop split

The `COT_ALL` README states that LSEG cannot supply this and that every row is
written with `Crop="All"` only. **That is out of date** — the current
`COT_ALL` parquets do contain fully populated `Old` and `Other` rows, and
every position column in them matches CFTC exactly. Only `Total OI` (and
`Non Rep Long`/`Short`, which are balancing figures derived from it) differs,
by at most 4 lots, so LSEG evidently derives Old/Other open interest rather
than reading it directly. Treat it as a rounding artefact, not a data gap; the
CFTC figures here are the exact published ones.

`Old`/`Other` rows are only meaningful for contracts with a designated crop
year. For SB, GC, SI and HG the CFTC reports `Old` equal to `All` and `Other`
as zero — that is the source data, not a gap.

### Other notes

- **Pct OI columns are recomputed** from positions / open interest at full
  precision rather than taken from CFTC's own `pct_of_oi_*` fields, which are
  rounded to 1dp. This is what `COT_ALL` does, so the two projects'
  percentage columns stay directly comparable.
- `Total OI` is `Float64` in `cot_disagg_futopt.parquet` and `Int64` in every
  other file. That inconsistency is inherited from `COT_ALL` and is reproduced
  deliberately, so a consumer concatenating both projects sees matching dtypes
  instead of a clash.

## The Legacy files

The Legacy report is the original COT format and has no `COT_ALL` counterpart,
so these two files use their own 39-column schema in the same style:
`Commodity, Crop, Date, Total OI`, then positions, trader counts,
concentration, `Pct OI *`, and `Px`. Its three trader classes are coarser than
the Disaggregated four:

| Legacy | roughly equals, in Disaggregated |
|---|---|
| Non-Commercial | Managed Money + Other Reportables |
| Commercial | Producer/Merchant + Swap Dealers |
| Non-Reportable | Non-Reportable (identical) |

**Why bother, when Disaggregated is finer:**

- **History.** Legacy futures-only starts **1986-01-15**, twenty years before
  the Disaggregated report exists. That is the only way to get long-run
  positioning percentiles for these markets.
- **Non-Commercial net is the headline "spec position"** most outside
  commentary and older research quotes, so it is what you reconcile against.
- It carries the **grain complex**, which the other two reports do not.

Verified against the Disaggregated files over the 7,392 overlapping
`Crop="All"` rows: `Total OI` and `Non Rep Long/Short` agree **100%**. The
category sums (Commercial ≈ Producer + Swap + Swap Spread, and so on) agree
exactly in roughly 70–77% of rows with a median difference of zero — the rest
differ because **the CFTC classifies each trader independently in the two
reports**, so a firm can be Commercial in Legacy and Managed Money in
Disaggregated. That is a documented property of the reports, not a mapping
error. Do not expect the two to reconcile row for row.

All four internal identities hold at 100.00% of rows:
`Tot Rept Long = NonComm Long + NonComm Spread + Comm Long`,
`Total OI = Tot Rept Long + Non Rep Long`, and the two short-side equivalents.

## The London softs (RC / LCC / LSU)

ICE Futures Europe publishes its own COT, free and unauthenticated, expressly
modelled on "the CFTC Long Format Disaggregated COT" — their words — so it
drops into this schema. Tuesday snapshot, published Friday 18:30 London.

Source is one CSV per year, all ICE contracts in each:
`https://www.ice.com/publicdocs/futures/COTHist{YYYY}.csv`. The current year's
file is **overwritten in place every Friday**, accumulating the year, so a
weekly update is one download. `ice_ingest.py` sends an `If-None-Match` with
the stored ETag and does nothing at all on a 304.

| | |
|---|---|
| Commodities | `RC` Robusta, `LCC` London Cocoa, `LSU` White Sugar |
| Rows | 1,869 per disagg file (623 each) |
| History | 2014-09-30 → 2026-09-01 |
| Written into | `cot_disagg_futopt.parquet` (ICE "Combined") and `cot_disagg_fut.parquet` (ICE "FutOnly") |

Validated against `LSEG/COT_ALL` over all 1,869 overlapping rows: `Total OI`,
Producer, MM and Other columns match **100%**, Swap and Non-Rep **99.95%**
(one week differs, evidently a revision one side has and the other does not).

### Four things this ingest has to handle

1. **ICE's `_Old` columns are not an old-crop split.** They hold the
   *previous week's* `_All` values — verified, they equal the prior row
   exactly, 100% of the time, evidently so the sheet can compute a
   week-on-week change. Mapping them to `Crop="Old"` would have silently
   passed last week's numbers off as old-crop data. ICE rows are therefore
   written as `Crop="All"` only, and `_Other` is blank in the source anyway.
2. **ICE renamed a column.** Up to 2025 the swap fields carry a doubled
   underscore (`Swap__Positions_Short_All`); from 2026 a single one. Column
   names are normalised by collapsing underscore runs, so both vintages land
   on the same name — otherwise Swap Short and Swap Spread go silently NaN
   for 2014-2025. The 2026 file also carries a UTF-8 BOM on its first column.
   There is a guard that logs an error if an expected column ever goes
   missing again, rather than emitting a column of NaN.
3. **`Tot_Rept_Positions_*` is blank** in ICE's file for the softs, so it is
   derived as the sum of the four category positions plus the three spread
   columns. Cross-checked against the other route (open interest minus
   non-reportable, ICE's own definition of the balancing figure): the two
   agree on 100% of rows. The residual `OI = Tot Rept + Non Rep` identity then
   holds to within 2 lots, mean 0.27 — ICE's own rounding in its 2014-2020
   figures, not a mapping error.
4. **Concentration is NaN** for these three. ICE computes Conc 4/8 for its
   energy contracts only — the same gap `LSEG/COT_ALL` has.
   `Traders Tot Rept Long/Short` is also left NaN: ICE does not publish it,
   and faking it as a category sum (what LSEG does) would put a different
   quantity in the same column as the CFTC rows' true distinct count.

`cftc_backfill.py` will not clobber these rows. It re-reads the file and
carries forward any commodity it does not itself produce, logging how many it
kept, so a full CFTC rebuild and the ICE ingest can run in either order.

### Not covered

History starts 2014-09-30. ICE's `COTHist2011`-`2013` files hold Brent and
Gasoil only, and the pre-ICE LIFFE softs history (2012-05 to 2014-09) sits in
`LIFFE_COT_Hist.csv` under a different 28-column layout that this script does
not read. `LSEG/COT_ALL` still reaches back to 2010 for these three, so it
remains the deeper source if those four extra years matter.

## Running it

```bash
python Code/cftc_backfill.py                  # full rebuild (~45s)
python Code/cftc_backfill.py --start 2015-01-01
python Code/cftc_ingest.py                    # weekly incremental
python Code/cftc_ingest.py --merge-px         # and refresh Px from COT_ALL

python Code/ice_ingest.py                     # weekly London softs
python Code/ice_ingest.py --full              # rebuild ICE rows from 2014
python Code/ice_ingest.py --full --force      # ...ignoring stored ETags

Automator
un.bat                             # both ingests + run_log.txt
```

`run.bat` is the weekly entry point. Schedule it for **Friday evening** —
CFTC releases 15:30 ET and ICE publishes 18:30 London, so roughly 23:30 IST
clears both. It is not yet registered with Task Scheduler.

The incremental run re-fetches the current report year and merges on
`(Commodity, Crop, Date)` with new rows winning, which is what applies CFTC's
in-year revisions to weeks already on file. It is idempotent — re-running it
against unchanged upstream data leaves the parquets byte-identical.

Only `pandas`, `requests` and `pyarrow` are needed. An app token is optional;
set `CFTC_APP_TOKEN` in the environment if the desk ever starts hitting 429s.

## Not done yet

- **Task Scheduler registration.** `Automator/run.bat` exists and runs clean
  end to end (exit 0), but nothing is scheduled yet. Registering it needs an
  elevated prompt:
  `schtasks /create /tn "Hardmine CFTC COT" /tr "<full path>\Automator\run.bat" /sc weekly /d FRI /st 23:30`
- **No email notification** on success or failure yet.
- **`Dashboard/`** — empty. `COT_ALL/Dashboard/cot_app.py` is a pure parquet
  consumer and should run against these files as-is, but that has not been
  tried.
