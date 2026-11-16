import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import requests


ROOT = Path(__file__).resolve().parents[2]
FINLAB_DIR = ROOT / "data" / "finlab_research"
PUBLIC_DIR = ROOT / "data" / "public_stock_price"
INPUT_JSON = Path(__file__).resolve().parent / "public_close_input.json"
API_URL = "https://api.finmindtrade.com/api/v4/data"
START_DATE = "2023-12-01"
APPEND_START = "2024-01-01"
END_DATE = date.today().isoformat()
MEMORY_SYMBOLS = [
    "2337", "2344", "2408", "2451", "3006", "3260", "3529",
    "4967", "5351", "6531", "6770", "8271", "8299",
]


def fetch_symbol(symbol):
    params = {
        "dataset": "TaiwanStockPrice",
        "data_id": symbol,
        "start_date": START_DATE,
        "end_date": END_DATE,
    }
    last_error = None
    for attempt in range(5):
        try:
            response = requests.get(API_URL, params=params, timeout=45)
            if response.status_code == 429:
                raise RuntimeError("rate limited")
            response.raise_for_status()
            payload = response.json()
            if payload.get("status") != 200:
                raise RuntimeError(payload.get("msg", "unknown API error"))
            rows = payload.get("data", [])
            return symbol, rows, None
        except Exception as exc:
            last_error = str(exc)
            time.sleep(2 ** attempt)
    return symbol, [], last_error


def clean_matrix(frame, headers):
    rows = [["日期"] + headers]
    for timestamp, row in frame.iterrows():
        values = []
        for value in row.tolist():
            if pd.isna(value):
                values.append(None)
            else:
                values.append(float(value))
        rows.append([timestamp.strftime("%Y-%m-%d")] + values)
    return rows


old_close = pd.read_parquet(FINLAB_DIR / "daily" / "close.parquet")
old_close.index = pd.to_datetime(old_close.index)
symbols = [str(symbol) for symbol in old_close.columns]

master = pd.read_parquet(FINLAB_DIR / "company_master.parquet")
name_by_symbol = {
    str(row["symbol"]): str(row["公司簡稱"])
    for _, row in master.iterrows()
}

records = []
failures = []
completed = 0
with ThreadPoolExecutor(max_workers=6) as executor:
    futures = {executor.submit(fetch_symbol, symbol): symbol for symbol in symbols}
    for future in as_completed(futures):
        symbol, rows, error = future.result()
        completed += 1
        if error:
            failures.append({"symbol": symbol, "error": error})
        else:
            records.extend(rows)
        if completed % 10 == 0 or completed == len(symbols):
            print(f"下載進度 {completed}/{len(symbols)}；失敗 {len(failures)}", flush=True)

if not records:
    raise RuntimeError("公開 API 沒有回傳任何股價資料")

long = pd.DataFrame.from_records(records)
long["date"] = pd.to_datetime(long["date"])
long["stock_id"] = long["stock_id"].astype(str)
long["close"] = pd.to_numeric(long["close"], errors="coerce")
long = long.drop_duplicates(subset=["date", "stock_id"], keep="last")
public_wide = long.pivot(index="date", columns="stock_id", values="close")
public_wide = public_wide.reindex(columns=symbols)

overlap_start = pd.Timestamp(START_DATE)
overlap_end = pd.Timestamp("2023-12-31")
common_dates = old_close.index.intersection(public_wide.index)
common_dates = common_dates[(common_dates >= overlap_start) & (common_dates <= overlap_end)]
old_overlap = old_close.loc[common_dates, symbols]
public_overlap = public_wide.loc[common_dates, symbols]
comparable = old_overlap.notna() & public_overlap.notna()
differences = (old_overlap - public_overlap).abs()
mismatches = comparable & (differences > 1e-9)
comparison_count = int(comparable.to_numpy().sum())
mismatch_count = int(mismatches.to_numpy().sum())

public_append = public_wide.loc[public_wide.index >= pd.Timestamp(APPEND_START)].copy()
combined = pd.concat([old_close, public_append], axis=0)
combined = combined[~combined.index.duplicated(keep="last")].sort_index()
combined = combined.reindex(columns=symbols)

PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
public_append.to_parquet(PUBLIC_DIR / "close_2024_onward.parquet")
combined.to_parquet(PUBLIC_DIR / "close_combined_2019_onward.parquet")

missing_symbols = [
    symbol for symbol in symbols
    if symbol not in public_append.columns or public_append[symbol].notna().sum() == 0
]

memory_headers = [
    f"{symbol} {name_by_symbol.get(symbol, '')}".strip()
    for symbol in MEMORY_SYMBOLS
]
all_headers = symbols

manifest = {
    "created_at": date.today().isoformat(),
    "source": "FinMind TaiwanStockPrice public API",
    "source_url": "https://api.finmindtrade.com/api/v4/data",
    "dataset": "TaiwanStockPrice",
    "original_source": "FinLab price:收盤價",
    "original_period": [
        old_close.index.min().strftime("%Y-%m-%d"),
        old_close.index.max().strftime("%Y-%m-%d"),
    ],
    "public_period": [
        public_append.index.min().strftime("%Y-%m-%d"),
        public_append.index.max().strftime("%Y-%m-%d"),
    ],
    "combined_period": [
        combined.index.min().strftime("%Y-%m-%d"),
        combined.index.max().strftime("%Y-%m-%d"),
    ],
    "companies": len(symbols),
    "public_trading_days": len(public_append),
    "combined_trading_days": len(combined),
    "overlap_comparisons": comparison_count,
    "overlap_mismatches": mismatch_count,
    "missing_public_symbols": missing_symbols,
    "request_failures": failures,
}
(PUBLIC_DIR / "manifest.json").write_text(
    json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
)

payload = {
    "meta": manifest,
    "memory": clean_matrix(combined[MEMORY_SYMBOLS], memory_headers),
    "all": clean_matrix(combined, all_headers),
}
INPUT_JSON.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

print(json.dumps(manifest, ensure_ascii=False, indent=2), flush=True)
print(INPUT_JSON, flush=True)
