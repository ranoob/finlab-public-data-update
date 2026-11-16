import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

import pandas as pd
import requests


ROOT = Path(__file__).resolve().parents[2]
FINLAB_DIR = ROOT / "data" / "finlab_research"
OUT_DIR = ROOT / "data" / "public_research_updates"
CACHE_DIR = OUT_DIR / "cache" / "official_volume"
INPUT_JSON = Path(__file__).resolve().parent / "research_updates_input.json"
USER_AGENT = "Mozilla/5.0 (compatible; academic-research/1.0)"
RATE_LOCKS = {"sii": threading.Lock(), "otc": threading.Lock()}
LAST_REQUEST = {"sii": 0.0, "otc": 0.0}


def fetch_json(url, params):
    error = None
    for attempt in range(3):
        try:
            time.sleep(0.4)
            response = requests.get(
                url,
                params=params,
                headers={"User-Agent": USER_AGENT},
                timeout=15,
            )
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            error = exc
            time.sleep(min(8, 2 ** attempt))
    raise RuntimeError(f"{url}: {error}")


def fetch_market_day(day, market, symbol_set):
    cache_file = CACHE_DIR / market / f"{day:%Y%m%d}.json"
    if cache_file.exists():
        return json.loads(cache_file.read_text(encoding="utf-8"))

    with RATE_LOCKS[market]:
        elapsed = time.monotonic() - LAST_REQUEST[market]
        if elapsed < 1.2:
            time.sleep(1.2 - elapsed)
        if market == "sii":
            payload = fetch_json(
                "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX",
                {"response": "json", "date": day.strftime("%Y%m%d"), "type": "ALLBUT0999"},
            )
        else:
            payload = fetch_json(
                "https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes",
                {"date": day.strftime("%Y/%m/%d"), "id": "", "response": "json"},
            )
        LAST_REQUEST[market] = time.monotonic()

    if market == "sii":
        tables = payload.get("tables", [])
        table = next(
            (item for item in tables if "證券代號" in item.get("fields", []) and "成交股數" in item.get("fields", [])),
            None,
        )
        if table is None:
            raise RuntimeError(f"TWSE {day:%Y-%m-%d} 找不到個股行情表")
        code_index = table["fields"].index("證券代號")
        volume_index = table["fields"].index("成交股數")
    else:
        tables = payload.get("tables", [])
        if not tables:
            raise RuntimeError(f"TPEx {day:%Y-%m-%d} 找不到個股行情表")
        table = tables[0]
        code_index = table["fields"].index("代號")
        volume_index = table["fields"].index("成交股數")

    records = []
    for row in table.get("data", []):
        symbol = str(row[code_index]).strip()
        if symbol not in symbol_set:
            continue
        raw = str(row[volume_index]).replace(",", "").strip()
        if raw and raw not in {"--", "-"}:
            records.append({"date": day.strftime("%Y-%m-%d"), "stock_id": symbol, "volume": int(raw)})

    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
    return records


old_volume = pd.read_parquet(FINLAB_DIR / "daily" / "volume_shares.parquet")
old_volume.index = pd.to_datetime(old_volume.index)
symbols = [str(symbol) for symbol in old_volume.columns]
symbol_set = set(symbols)

# Yahoo 僅用來建立交易日清單，不使用其成交量數字。
candidate_dates = set()
for cache_file in (OUT_DIR / "cache" / "yahoo_volume").glob("*.json"):
    for row in json.loads(cache_file.read_text(encoding="utf-8")):
        day = pd.Timestamp(row["date"])
        if day >= pd.Timestamp("2023-12-01"):
            candidate_dates.add(day)
candidate_dates = sorted(candidate_dates)

jobs = [(day, market) for day in candidate_dates for market in ("sii", "otc")]
records = []
failures = []
CACHE_DIR.mkdir(parents=True, exist_ok=True)
with ThreadPoolExecutor(max_workers=4) as executor:
    futures = {
        executor.submit(fetch_market_day, day, market, symbol_set): (day, market)
        for day, market in jobs
    }
    for index, future in enumerate(as_completed(futures), start=1):
        day, market = futures[future]
        try:
            records.extend(future.result())
        except Exception as exc:
            failures.append({"date": day.strftime("%Y-%m-%d"), "market": market, "error": str(exc)})
        if index % 50 == 0 or index == len(futures):
            print(f"官方成交量 {index}/{len(futures)}；失敗 {len(failures)}", flush=True)

if not records:
    raise RuntimeError("官方成交量沒有回傳資料")

long = pd.DataFrame(records)
long["date"] = pd.to_datetime(long["date"])
public = long.pivot_table(index="date", columns="stock_id", values="volume", aggfunc="last").reindex(columns=symbols)

overlap = old_volume.index.intersection(public.index)
comparable = old_volume.loc[overlap].notna() & public.loc[overlap].notna()
diff = (old_volume.loc[overlap] - public.loc[overlap]).abs()
mismatches = int((comparable & (diff > 0.5)).to_numpy().sum())
comparisons = int(comparable.to_numpy().sum())

append = public.loc[public.index > old_volume.index.max()]
combined = pd.concat([old_volume, append]).sort_index()
combined.to_parquet(OUT_DIR / "volume_shares_combined.parquet")

manifest_path = OUT_DIR / "manifest.json"
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
manifest["updated"]["volume"] = [
    combined.index.min().strftime("%Y-%m-%d"),
    combined.index.max().strftime("%Y-%m-%d"),
]
manifest["checks"]["volume_overlap_comparisons"] = comparisons
manifest["checks"]["volume_overlap_mismatches"] = mismatches
manifest["failures"]["volume"] = failures
manifest["volume_source"] = "TWSE MI_INDEX and TPEx dailyQuotes; Yahoo was used only for the trading-day calendar."
manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

payload = json.loads(INPUT_JSON.read_text(encoding="utf-8"))
payload["meta"] = manifest
payload["sources"]["volume"] = (
    "資料來源：2019-10～2023-12 FinLab price:成交股數；2024 起臺灣證券交易所每日收盤行情 MI_INDEX "
    "（https://www.twse.com.tw/exchangeReport/MI_INDEX）與證券櫃檯買賣中心上櫃股票行情 "
    "（https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes）。單位：股。"
)
rows = [["日期"] + symbols]
for index, row in combined.iterrows():
    values = [None if pd.isna(value) else int(round(float(value))) for value in row.tolist()]
    rows.append([pd.Timestamp(index).strftime("%Y-%m-%d")] + values)
payload["volume"] = rows
INPUT_JSON.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

print(json.dumps({
    "created_at": date.today().isoformat(),
    "trading_days": len(candidate_dates),
    "jobs": len(jobs),
    "failures": failures,
    "overlap_comparisons": comparisons,
    "overlap_mismatches": mismatches,
    "updated_through": combined.index.max().strftime("%Y-%m-%d"),
}, ensure_ascii=False, indent=2), flush=True)
