"""Download the FinLab portion of the investor-attention research dataset.

The research period is 2020-2025. Daily data start in 2019-10 so the first
events have enough observations for the [-250, -31] estimation window. Data
through 2026-10-20 are retained for the out-of-sample check described in the
research framework.

Run from the project root:
    .venv/bin/python code/fetch_finlab_research_data.py

Optional mechanism variables (institutional investors, margin and day trading):
    .venv/bin/python code/fetch_finlab_research_data.py --include-mechanism
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from finlab import data


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = PROJECT_ROOT / "data" / "finlab_research"
START_DATE = pd.Timestamp("2019-10-01")
END_DATE = pd.Timestamp("2026-10-20")

MEMORY_CORE = {"2408", "2344", "2337", "3006", "5351"}
MEMORY_EXTENDED = {
    "8299",
    "3260",
    "2451",
    "4967",
    "8271",
    "3529",
    "6531",
}
BOUNDARY = {"6770"}

CORE_DAILY_FIELDS = {
    "price:開盤價": "open",
    "price:最高價": "high",
    "price:最低價": "low",
    "price:收盤價": "close",
    "price:成交股數": "volume_shares",
    "price:成交金額": "turnover_twd",
    "etl:adj_open": "adj_open",
    "etl:adj_high": "adj_high",
    "etl:adj_low": "adj_low",
    "etl:adj_close": "adj_close",
    "etl:market_value": "market_value_twd",
}

MONTHLY_FIELDS = {
    "monthly_revenue:當月營收": "monthly_revenue",
    "monthly_revenue:去年當月營收": "monthly_revenue_last_year",
}

QUARTERLY_FIELDS = {
    "financial_statement:每股盈餘": "eps",
}

MECHANISM_FIELDS = {
    "institutional_investors_trading_summary:外陸資買賣超股數(不含外資自營商)": "foreign_net_shares",
    "institutional_investors_trading_summary:投信買賣超股數": "investment_trust_net_shares",
    "institutional_investors_trading_summary:自營商買賣超股數(自行買賣)": "dealer_proprietary_net_shares",
    "institutional_investors_trading_summary:自營商買賣超股數(避險)": "dealer_hedging_net_shares",
    "margin_transactions:融資今日餘額": "margin_balance_shares",
    "margin_transactions:融券今日餘額": "short_balance_shares",
    "intraday_trading:當日沖銷交易成交股數": "day_trade_volume_shares",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--include-mechanism",
        action="store_true",
        help="also download the optional H4 mechanism variables",
    )
    parser.add_argument(
        "--force-download",
        action="store_true",
        help="ask FinLab to refresh cached datasets before saving",
    )
    return parser.parse_args()


def log(message: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {message}", flush=True)


def ensure_datetime_index(frame: pd.DataFrame) -> pd.DataFrame:
    result = pd.DataFrame(frame).copy()
    if not isinstance(result.index, pd.DatetimeIndex):
        result.index = pd.to_datetime(result.index, errors="coerce")
    result = result.loc[result.index.notna()]
    result.index.name = "date"
    return result.sort_index()


def slice_dates(frame: pd.DataFrame) -> pd.DataFrame:
    result = ensure_datetime_index(frame)
    return result.loc[(result.index >= START_DATE) & (result.index <= END_DATE)]


def slice_quarters(frame: pd.DataFrame) -> pd.DataFrame:
    """Keep fiscal-quarter labels without converting them to artificial dates."""
    result = pd.DataFrame(frame).copy()
    labels = result.index.astype(str).str.replace("-", "", regex=False)
    periods = pd.PeriodIndex(labels, freq="Q")
    keep = (periods >= pd.Period("2019Q4")) & (periods <= pd.Period("2026Q4"))
    result = result.loc[keep]
    result.index = periods[keep].astype(str)
    result.index.name = "fiscal_quarter"
    return result


def select_stock_columns(frame: pd.DataFrame, tickers: list[str]) -> pd.DataFrame:
    result = pd.DataFrame(frame).copy()
    result.columns = result.columns.astype(str)
    available = [ticker for ticker in tickers if ticker in result.columns]
    return result.loc[:, available]


def write_parquet(frame: pd.DataFrame, path: Path) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, compression="zstd")
    check = pd.read_parquet(path)
    if check.shape != frame.shape:
        raise RuntimeError(
            f"Parquet verification failed for {path}: {check.shape} != {frame.shape}"
        )
    info: dict[str, Any] = {
        "path": str(path.relative_to(PROJECT_ROOT)),
        "rows": int(frame.shape[0]),
        "columns": int(frame.shape[1]),
        "bytes": path.stat().st_size,
    }
    if len(frame.index):
        info["first_index"] = str(frame.index.min())
        info["last_index"] = str(frame.index.max())
    return info


def fetch(key: str, force_download: bool) -> pd.DataFrame:
    log(f"FinLab: {key}")
    return pd.DataFrame(data.get(key, force_download=force_download))


def fetch_wide_field(
    key: str,
    output_name: str,
    folder: str,
    tickers: list[str],
    force_download: bool,
    index_kind: str = "date",
) -> tuple[dict[str, Any] | None, pd.DataFrame | None]:
    try:
        frame = fetch(key, force_download)
        frame = select_stock_columns(frame, tickers)
        frame = slice_quarters(frame) if index_kind == "quarter" else slice_dates(frame)
        path = OUTPUT_ROOT / folder / f"{output_name}.parquet"
        info = write_parquet(frame, path)
        info["finlab_key"] = key
        log(f"saved {path.relative_to(PROJECT_ROOT)} {frame.shape}")
        return info, frame
    except Exception as exc:
        log(f"WARNING: {key} failed: {type(exc).__name__}: {exc}")
        return None, None


def build_company_master(
    company_info: pd.DataFrame,
    close: pd.DataFrame,
) -> pd.DataFrame:
    master = company_info.copy()
    master["symbol"] = master["symbol"].astype(str)
    master = master.loc[
        master["產業類別"].astype(str).eq("半導體業")
        & master["市場別"].astype(str).isin(["sii", "otc"])
    ].copy()

    close = select_stock_columns(close, master["symbol"].tolist())
    close = slice_dates(close)
    availability = []
    for ticker in master["symbol"]:
        series = close[ticker].dropna() if ticker in close.columns else pd.Series(dtype=float)
        availability.append(
            {
                "symbol": ticker,
                "price_first_date": series.index.min() if len(series) else pd.NaT,
                "price_last_date": series.index.max() if len(series) else pd.NaT,
                "price_observations": int(series.shape[0]),
                "pre_2020_observations": int((series.index < "2020-01-01").sum()),
            }
        )
    availability_frame = pd.DataFrame(availability)
    master = master.merge(availability_frame, on="symbol", how="left")

    def group_for(ticker: str) -> str:
        if ticker in MEMORY_CORE:
            return "memory_core"
        if ticker in MEMORY_EXTENDED:
            return "memory_extended"
        if ticker in BOUNDARY:
            return "boundary_review"
        return "semiconductor_control_candidate"

    master["research_group"] = master["symbol"].map(group_for)
    master["document_sample"] = master["symbol"].isin(
        MEMORY_CORE | MEMORY_EXTENDED | BOUNDARY
    )
    master["eligible_for_2020_estimation"] = master["pre_2020_observations"].ge(120)

    ordered = [
        "symbol",
        "公司簡稱",
        "公司名稱",
        "產業類別",
        "市場別",
        "上市日期",
        "上櫃日期",
        "research_group",
        "document_sample",
        "eligible_for_2020_estimation",
        "price_first_date",
        "price_last_date",
        "price_observations",
        "pre_2020_observations",
    ]
    ordered += [column for column in master.columns if column not in ordered]
    return master.loc[:, ordered].sort_values(["research_group", "symbol"])


def save_disclosure_dates(
    tickers: list[str], force_download: bool
) -> dict[str, Any] | None:
    key = "etl:financial_statements_disclosure_dates"
    try:
        frame = fetch(key, force_download)
        frame.columns = frame.columns.astype(str)
        frame = frame.loc[:, [ticker for ticker in tickers if ticker in frame.columns]]
        labels = frame.index.astype(str).str.replace("-", "", regex=False)
        periods = pd.PeriodIndex(labels, freq="Q")
        quarter_keep = (periods >= pd.Period("2019Q4")) & (
            periods <= pd.Period("2026Q4")
        )
        frame = frame.loc[quarter_keep]
        periods = periods[quarter_keep]
        values = frame.apply(lambda col: pd.to_datetime(col, errors="coerce"))
        values.index = periods.astype(str)
        values.index.name = "fiscal_quarter"
        path = OUTPUT_ROOT / "events" / "financial_statement_disclosure_dates.parquet"
        info = write_parquet(values, path)
        info["finlab_key"] = key
        return info
    except Exception as exc:
        log(f"WARNING: {key} failed: {type(exc).__name__}: {exc}")
        return None


def save_investor_conferences(
    tickers: list[str], force_download: bool
) -> dict[str, Any] | None:
    key = "investors_conference"
    try:
        frame = fetch(key, force_download)
        ticker_column = "stock_id" if "stock_id" in frame.columns else "symbol"
        frame[ticker_column] = frame[ticker_column].astype(str)
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        frame = frame.loc[
            frame[ticker_column].isin(tickers)
            & frame["date"].between(START_DATE, END_DATE)
        ].copy()
        frame = frame.sort_values([ticker_column, "date"])
        path = OUTPUT_ROOT / "events" / "investor_conferences.parquet"
        info = write_parquet(frame.reset_index(drop=True), path)
        info["finlab_key"] = key
        return info
    except Exception as exc:
        log(f"WARNING: {key} failed: {type(exc).__name__}: {exc}")
        return None


def save_benchmarks(
    close: pd.DataFrame, force_download: bool
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    benchmark_fields = {
        "benchmark_return:發行量加權股價報酬指數": "taiex_total_return_index",
        "taiex_total_index:收盤指數": "taiex_price_index",
    }
    for key, name in benchmark_fields.items():
        try:
            frame = slice_dates(fetch(key, force_download))
            path = OUTPUT_ROOT / "benchmarks" / f"{name}.parquet"
            info = write_parquet(frame, path)
            info["finlab_key"] = key
            records.append(info)
        except Exception as exc:
            log(f"WARNING: {key} failed: {type(exc).__name__}: {exc}")

    close.columns = close.columns.astype(str)
    if "0050" in close.columns:
        proxy = slice_dates(close.loc[:, ["0050"]]).rename(columns={"0050": "0050"})
        path = OUTPUT_ROOT / "benchmarks" / "0050_close_proxy.parquet"
        info = write_parquet(proxy, path)
        info["finlab_key"] = "price:收盤價"
        info["note"] = "ETF price proxy; not a substitute for the TAIEX total-return index"
        records.append(info)
    return records


def main() -> None:
    args = parse_args()
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    data.truncate_start = START_DATE.strftime("%Y-%m-%d")

    manifest: dict[str, Any] = {
        "created_at": datetime.now().astimezone().isoformat(),
        "research_period": ["2020-01-01", "2025-12-31"],
        "download_window": [str(START_DATE.date()), str(END_DATE.date())],
        "source_document": "/Users/hankchou/Documents/NTHU/2026_fall/GE_bigdata/data/研究架構_v0.1.pdf",
        "notes": [
            "The exact 25-company comparison sample was not listed in the PDF; all listed/OTC semiconductor companies are retained as matching candidates.",
            "Google Trends, DRAM prices and exact MOPS announcement timestamps are outside this FinLab download.",
            "FinLab account permissions can shorten some datasets; inspect each file's first_index and last_index below.",
        ],
        "files": [],
        "failures": [],
    }

    log("loading company master")
    company_info = fetch("company_basic_info", args.force_download)
    close_all = fetch("price:收盤價", args.force_download)
    master = build_company_master(company_info, close_all)
    tickers = sorted(master.loc[master["price_observations"].gt(0), "symbol"].tolist())
    log(f"semiconductor universe with price data: {len(tickers)} companies")

    master_path = OUTPUT_ROOT / "company_master.parquet"
    manifest["files"].append(write_parquet(master, master_path))
    sample_path = OUTPUT_ROOT / "document_memory_sample.parquet"
    manifest["files"].append(
        write_parquet(master.loc[master["document_sample"]].copy(), sample_path)
    )

    cached_close = select_stock_columns(close_all, tickers)
    cached_close = slice_dates(cached_close)
    for key, name in CORE_DAILY_FIELDS.items():
        if key == "price:收盤價":
            path = OUTPUT_ROOT / "daily" / f"{name}.parquet"
            info = write_parquet(cached_close, path)
            info["finlab_key"] = key
            manifest["files"].append(info)
            continue
        info, _ = fetch_wide_field(
            key, name, "daily", tickers, args.force_download
        )
        if info:
            manifest["files"].append(info)
        else:
            manifest["failures"].append(key)

    for key, name in MONTHLY_FIELDS.items():
        info, _ = fetch_wide_field(
            key, name, "monthly", tickers, args.force_download
        )
        if info:
            manifest["files"].append(info)
        else:
            manifest["failures"].append(key)

    for key, name in QUARTERLY_FIELDS.items():
        info, _ = fetch_wide_field(
            key,
            name,
            "quarterly",
            tickers,
            args.force_download,
            index_kind="quarter",
        )
        if info:
            manifest["files"].append(info)
        else:
            manifest["failures"].append(key)

    disclosure_info = save_disclosure_dates(tickers, args.force_download)
    if disclosure_info:
        manifest["files"].append(disclosure_info)
    else:
        manifest["failures"].append("etl:financial_statements_disclosure_dates")

    conference_info = save_investor_conferences(tickers, args.force_download)
    if conference_info:
        manifest["files"].append(conference_info)
    else:
        manifest["failures"].append("investors_conference")

    manifest["files"].extend(save_benchmarks(close_all, args.force_download))

    if args.include_mechanism:
        for key, name in MECHANISM_FIELDS.items():
            info, _ = fetch_wide_field(
                key, name, "mechanism", tickers, args.force_download
            )
            if info:
                manifest["files"].append(info)
            else:
                manifest["failures"].append(key)

    manifest["universe_count"] = len(tickers)
    manifest["memory_core"] = sorted(MEMORY_CORE)
    manifest["memory_extended"] = sorted(MEMORY_EXTENDED)
    manifest["boundary_review"] = sorted(BOUNDARY)
    manifest_path = OUTPUT_ROOT / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log(f"done: {manifest_path.relative_to(PROJECT_ROOT)}")
    log(f"files: {len(manifest['files'])}; failures: {len(manifest['failures'])}")


if __name__ == "__main__":
    main()
