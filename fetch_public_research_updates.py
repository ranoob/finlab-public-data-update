import html
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests


ROOT = Path(__file__).resolve().parents[2]
FINLAB_DIR = ROOT / "data" / "finlab_research"
OUT_DIR = ROOT / "data" / "public_research_updates"
CACHE_DIR = OUT_DIR / "cache"
INPUT_JSON = Path(__file__).resolve().parent / "research_updates_input.json"
FINMIND_URL = "https://api.finmindtrade.com/api/v4/data"
MOPS_BASE = "https://mopsov.twse.com.tw"
YAHOO_BASE = "https://query1.finance.yahoo.com/v8/finance/chart"
USER_AGENT = "Mozilla/5.0 (compatible; academic-research/1.0)"
TODAY = pd.Timestamp(date.today())


def clean_text(value):
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return None
    return text


def clean_number(value):
    text = clean_text(value)
    if text is None or text in {"--", "-"}:
        return np.nan
    try:
        return float(text.replace(",", ""))
    except ValueError:
        return np.nan


def strip_cell(fragment):
    text = re.sub(r"<script.*?</script>", "", fragment, flags=re.I | re.S)
    text = re.sub(r"<style.*?</style>", "", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(html.unescape(text).replace("\xa0", " ").split())


def roc_to_date(value):
    match = re.fullmatch(r"(\d{2,3})/(\d{1,2})/(\d{1,2})", value.strip())
    if not match:
        return None
    year, month, day = map(int, match.groups())
    return pd.Timestamp(year + 1911, month, day)


def fetch_with_retry(method, url, *, params=None, data=None, encoding=None, attempts=5):
    error = None
    for attempt in range(attempts):
        try:
            response = requests.request(
                method,
                url,
                params=params,
                data=data,
                headers={"User-Agent": USER_AGENT},
                timeout=60,
            )
            response.raise_for_status()
            if encoding:
                response.encoding = encoding
                return response.text
            return response
        except Exception as exc:
            error = exc
            time.sleep(min(16, 2 ** attempt))
    raise RuntimeError(f"{url}: {error}")


old_close = pd.read_parquet(FINLAB_DIR / "daily" / "close.parquet")
symbols = [str(symbol) for symbol in old_close.columns]
symbol_set = set(symbols)
master = pd.read_parquet(FINLAB_DIR / "company_master.parquet")
master["symbol"] = master["symbol"].astype(str)
master = master.drop_duplicates("symbol").set_index("symbol")
market_by_symbol = master["市場別"].astype(str).to_dict()


# 月營收：MOPS 歷史檔，一個市場／月份一個公開頁面。
def fetch_revenue_month(year, month, market):
    roc_year = year - 1911
    url = f"{MOPS_BASE}/nas/t21/{market}/t21sc03_{roc_year}_{month}_0.html"
    text = fetch_with_retry("GET", url, encoding="big5")
    rows = []
    for row_html in re.findall(r"<tr\s+align=right>(.*?)</tr>", text, flags=re.I | re.S):
        cells = [
            strip_cell(cell)
            for cell in re.findall(r"<td\b[^>]*>(.*?)</td>", row_html, flags=re.I | re.S)
        ]
        if len(cells) < 5 or not re.fullmatch(r"\d{4}", cells[0]):
            continue
        if cells[0] not in symbol_set:
            continue
        rows.append({
            "date": pd.Timestamp(year, month, 1),
            "stock_id": cells[0],
            "revenue": clean_number(cells[2]),
            "revenue_last_year": clean_number(cells[4]),
        })
    return rows


revenue_start = pd.Timestamp("2023-11-01")
revenue_end = TODAY.to_period("M").to_timestamp() - pd.offsets.MonthBegin(1)
revenue_jobs = []
cursor = revenue_start
while cursor <= revenue_end:
    for market in ("sii", "otc"):
        revenue_jobs.append((cursor.year, cursor.month, market))
    cursor += pd.offsets.MonthBegin(1)

revenue_records = []
revenue_failures = []
with ThreadPoolExecutor(max_workers=4) as executor:
    futures = {
        executor.submit(fetch_revenue_month, year, month, market): (year, month, market)
        for year, month, market in revenue_jobs
    }
    for index, future in enumerate(as_completed(futures), start=1):
        job = futures[future]
        try:
            revenue_records.extend(future.result())
        except Exception as exc:
            revenue_failures.append({"job": job, "error": str(exc)})
        if index % 10 == 0 or index == len(futures):
            print(f"月營收 {index}/{len(futures)}；失敗 {len(revenue_failures)}", flush=True)

revenue_long = pd.DataFrame(revenue_records)
if revenue_long.empty:
    raise RuntimeError("MOPS 月營收沒有回傳資料")
revenue_long = revenue_long.drop_duplicates(["date", "stock_id"], keep="last")
revenue_public = revenue_long.pivot(index="date", columns="stock_id", values="revenue").reindex(columns=symbols)
revenue_last_public = revenue_long.pivot(index="date", columns="stock_id", values="revenue_last_year").reindex(columns=symbols)

old_revenue = pd.read_parquet(FINLAB_DIR / "monthly" / "monthly_revenue.parquet")
old_revenue_last = pd.read_parquet(FINLAB_DIR / "monthly" / "monthly_revenue_last_year.parquet")
old_revenue.index = (pd.to_datetime(old_revenue.index).to_period("M") - 1).to_timestamp()
old_revenue_last.index = (pd.to_datetime(old_revenue_last.index).to_period("M") - 1).to_timestamp()
old_revenue = old_revenue.reindex(columns=symbols)
old_revenue_last = old_revenue_last.reindex(columns=symbols)

overlap_months = old_revenue.index.intersection(revenue_public.index)
revenue_comparable = old_revenue.loc[overlap_months].notna() & revenue_public.loc[overlap_months].notna()
revenue_diff = (old_revenue.loc[overlap_months] - revenue_public.loc[overlap_months]).abs()
revenue_mismatches = int((revenue_comparable & (revenue_diff > 1e-9)).to_numpy().sum())
revenue_comparisons = int(revenue_comparable.to_numpy().sum())

revenue_append = revenue_public.loc[revenue_public.index > old_revenue.index.max()]
revenue_last_append = revenue_last_public.loc[revenue_last_public.index > old_revenue_last.index.max()]
revenue_combined = pd.concat([old_revenue, revenue_append]).sort_index()
revenue_last_combined = pd.concat([old_revenue_last, revenue_last_append]).sort_index()


# EPS：FinMind 免費單一股票查詢，保留快取以便中斷後續跑。
eps_cache = CACHE_DIR / "eps"
eps_cache.mkdir(parents=True, exist_ok=True)


def fetch_eps(symbol):
    cache_file = eps_cache / f"{symbol}.json"
    if cache_file.exists():
        return symbol, json.loads(cache_file.read_text(encoding="utf-8")), None
    params = {
        "dataset": "TaiwanStockFinancialStatements",
        "data_id": symbol,
        "start_date": "2023-09-30",
        "end_date": TODAY.strftime("%Y-%m-%d"),
    }
    error = None
    for attempt in range(6):
        try:
            response = fetch_with_retry("GET", FINMIND_URL, params=params, attempts=1)
            payload = response.json()
            if payload.get("status") != 200:
                raise RuntimeError(payload.get("msg", "FinMind API error"))
            data = payload.get("data", [])
            cache_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            return symbol, data, None
        except Exception as exc:
            error = str(exc)
            time.sleep(min(30, 2 ** attempt))
    return symbol, [], error


eps_records = []
eps_failures = []
with ThreadPoolExecutor(max_workers=6) as executor:
    futures = {executor.submit(fetch_eps, symbol): symbol for symbol in symbols}
    for index, future in enumerate(as_completed(futures), start=1):
        symbol, rows, error = future.result()
        if error:
            eps_failures.append({"symbol": symbol, "error": error})
        else:
            for row in rows:
                if row.get("type") == "EPS":
                    eps_records.append(row)
        if index % 10 == 0 or index == len(futures):
            print(f"EPS {index}/{len(futures)}；失敗 {len(eps_failures)}", flush=True)

eps_long = pd.DataFrame(eps_records)
if eps_long.empty:
    raise RuntimeError("FinMind EPS 沒有回傳資料")
eps_long["date"] = pd.to_datetime(eps_long["date"])
eps_long["stock_id"] = eps_long["stock_id"].astype(str)
eps_long["quarter"] = eps_long["date"].dt.to_period("Q").astype(str)
eps_long["value"] = pd.to_numeric(eps_long["value"], errors="coerce")
eps_public = eps_long.pivot_table(index="quarter", columns="stock_id", values="value", aggfunc="last").reindex(columns=symbols)

old_eps = pd.read_parquet(FINLAB_DIR / "quarterly" / "eps.parquet").reindex(columns=symbols)
eps_overlap = old_eps.index.intersection(eps_public.index)
eps_comparable = old_eps.loc[eps_overlap].notna() & eps_public.loc[eps_overlap].notna()
eps_diff = (old_eps.loc[eps_overlap] - eps_public.loc[eps_overlap]).abs()
eps_mismatches = int((eps_comparable & (eps_diff > 0.011)).to_numpy().sum())
eps_comparisons = int(eps_comparable.to_numpy().sum())
eps_append = eps_public.loc[~eps_public.index.isin(old_eps.index)]
eps_combined = pd.concat([old_eps, eps_append]).sort_index()


# 成交量：Yahoo Finance 公開 chart endpoint；以 2023-12 重疊區間核對 FinLab。
volume_cache = CACHE_DIR / "yahoo_volume"
volume_cache.mkdir(parents=True, exist_ok=True)
period1 = int(pd.Timestamp("2023-12-01", tz="UTC").timestamp())
period2 = int((TODAY + pd.Timedelta(days=2)).tz_localize("UTC").timestamp())


def fetch_yahoo_volume(symbol):
    cache_file = volume_cache / f"{symbol}.json"
    if cache_file.exists():
        return symbol, json.loads(cache_file.read_text(encoding="utf-8")), None
    suffix = ".TW" if market_by_symbol.get(symbol) == "sii" else ".TWO"
    ticker = f"{symbol}{suffix}"
    url = f"{YAHOO_BASE}/{ticker}"
    params = {"period1": period1, "period2": period2, "interval": "1d", "events": "history"}
    error = None
    for attempt in range(5):
        try:
            response = fetch_with_retry("GET", url, params=params, attempts=1)
            payload = response.json()
            result = payload["chart"]["result"][0]
            timestamps = result.get("timestamp", [])
            volumes = result.get("indicators", {}).get("quote", [{}])[0].get("volume", [])
            rows = []
            for stamp, volume in zip(timestamps, volumes):
                rows.append({
                    "date": datetime.fromtimestamp(stamp, tz=timezone.utc).date().isoformat(),
                    "stock_id": symbol,
                    "volume": volume,
                })
            cache_file.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
            return symbol, rows, None
        except Exception as exc:
            error = str(exc)
            time.sleep(min(16, 2 ** attempt))
    return symbol, [], error


volume_records = []
volume_failures = []
with ThreadPoolExecutor(max_workers=6) as executor:
    futures = {executor.submit(fetch_yahoo_volume, symbol): symbol for symbol in symbols}
    for index, future in enumerate(as_completed(futures), start=1):
        symbol, rows, error = future.result()
        if error:
            volume_failures.append({"symbol": symbol, "error": error})
        else:
            volume_records.extend(rows)
        if index % 10 == 0 or index == len(futures):
            print(f"成交量 {index}/{len(futures)}；失敗 {len(volume_failures)}", flush=True)

volume_long = pd.DataFrame(volume_records)
if volume_long.empty:
    raise RuntimeError("Yahoo Finance 成交量沒有回傳資料")
volume_long["date"] = pd.to_datetime(volume_long["date"])
volume_long["volume"] = pd.to_numeric(volume_long["volume"], errors="coerce")
volume_public = volume_long.pivot_table(index="date", columns="stock_id", values="volume", aggfunc="last").reindex(columns=symbols)
old_volume = pd.read_parquet(FINLAB_DIR / "daily" / "volume_shares.parquet").reindex(columns=symbols)
old_volume.index = pd.to_datetime(old_volume.index)
volume_overlap = old_volume.index.intersection(volume_public.index)
volume_comparable = old_volume.loc[volume_overlap].notna() & volume_public.loc[volume_overlap].notna()
volume_diff = (old_volume.loc[volume_overlap] - volume_public.loc[volume_overlap]).abs()
volume_mismatches = int((volume_comparable & (volume_diff > 0.5)).to_numpy().sum())
volume_comparisons = int(volume_comparable.to_numpy().sum())
volume_append = volume_public.loc[volume_public.index > old_volume.index.max()]
volume_combined = pd.concat([old_volume, volume_append]).sort_index()


# 法說會：MOPS 法人說明會一覽表，一個市場／月份一個查詢。
def fetch_conference_month(year, month, market):
    data = {
        "encodeURIComponent": 1,
        "step": 1,
        "firstin": "ture",
        "off": 1,
        "TYPEK": market,
        "year": year - 1911,
        "month": f"{month:02d}",
        "co_id": "",
    }
    text = fetch_with_retry(
        "POST",
        f"{MOPS_BASE}/mops/web/ajax_t100sb02_1",
        data=data,
        encoding="utf-8",
    )
    records = []
    row_pattern = r"<tr class='(?:even|odd)' data-type='body'\s*>(.*?)</tr>"
    for row_html in re.findall(row_pattern, text, flags=re.I | re.S):
        cells = [
            strip_cell(cell)
            for cell in re.findall(r"<td\b[^>]*>(.*?)</td>", row_html, flags=re.I | re.S)
        ]
        if len(cells) < 11 or cells[0] not in symbol_set:
            continue
        event_date = roc_to_date(cells[2])
        if event_date is None:
            continue
        records.append({
            "symbol": cells[0],
            "公司名稱": cells[1],
            "date": event_date,
            "召開法人說明會時間": cells[3],
            "召開法人說明會地點": cells[4],
            "法人說明會擇要訊息": cells[5],
            "公司網站是否提供法人說明會相關資訊": cells[8],
            "影音連結資訊": cells[9],
            "其他應敘明事項": cells[10],
            "市場別": market,
        })
    return records


conference_jobs = []
cursor = pd.Timestamp("2024-01-01")
conference_end = TODAY.to_period("M").to_timestamp()
while cursor <= conference_end:
    for market in ("sii", "otc"):
        conference_jobs.append((cursor.year, cursor.month, market))
    cursor += pd.offsets.MonthBegin(1)

conference_records = []
conference_failures = []
with ThreadPoolExecutor(max_workers=4) as executor:
    futures = {
        executor.submit(fetch_conference_month, year, month, market): (year, month, market)
        for year, month, market in conference_jobs
    }
    for index, future in enumerate(as_completed(futures), start=1):
        job = futures[future]
        try:
            conference_records.extend(future.result())
        except Exception as exc:
            conference_failures.append({"job": job, "error": str(exc)})
        if index % 10 == 0 or index == len(futures):
            print(f"法說會 {index}/{len(futures)}；失敗 {len(conference_failures)}", flush=True)

conference_public = pd.DataFrame(conference_records)
old_conference = pd.read_parquet(FINLAB_DIR / "events" / "investor_conferences.parquet")
old_selected = pd.DataFrame({
    "symbol": old_conference["symbol"].astype(str),
    "公司名稱": old_conference["公司名稱"],
    "date": pd.to_datetime(old_conference["date"]),
    "召開法人說明會時間": old_conference["召開法人說明會時間"],
    "召開法人說明會地點": old_conference["召開法人說明會地點"],
    "法人說明會擇要訊息": old_conference["法人說明會擇要訊息"],
    "公司網站是否提供法人說明會相關資訊": old_conference["公司網站是否提供法人說明會相關資訊"],
    "影音連結資訊": old_conference["影音連結資訊(國內自辦應揭露，受邀參加可自願揭露)"],
    "其他應敘明事項": old_conference["其他應敘明事項"],
    "市場別": old_conference["市場別"],
})
conference_combined = pd.concat([old_selected, conference_public], ignore_index=True)
conference_combined = conference_combined[conference_combined["symbol"].isin(symbol_set)]
conference_combined = conference_combined.drop_duplicates(
    ["symbol", "date", "召開法人說明會時間", "召開法人說明會地點", "法人說明會擇要訊息"],
    keep="last",
).sort_values(["date", "symbol", "召開法人說明會時間"], kind="stable")


# 尚未能以免費來源精確補齊的資料保留原值。
market_value = pd.read_parquet(FINLAB_DIR / "daily" / "market_value_twd.parquet").reindex(columns=symbols)
market_value.index = pd.to_datetime(market_value.index)
disclosure = pd.read_parquet(FINLAB_DIR / "events" / "financial_statement_disclosure_dates.parquet").reindex(columns=symbols)


def matrix_from_wide(frame, index_label, date_index=False, number_decimals=None):
    header = [index_label] + symbols
    rows = [header]
    for index, row in frame.iterrows():
        if date_index:
            index_value = pd.Timestamp(index).strftime("%Y-%m-%d")
        else:
            index_value = str(index)
        values = []
        for value in row.tolist():
            if pd.isna(value):
                values.append(None)
            else:
                numeric = float(value)
                if number_decimals == 0:
                    numeric = int(round(numeric))
                values.append(numeric)
        rows.append([index_value] + values)
    return rows


def matrix_from_disclosure(frame):
    rows = [["財務季度"] + symbols]
    for index, row in frame.iterrows():
        values = []
        for value in row.tolist():
            if pd.isna(value):
                values.append(None)
            else:
                values.append(pd.Timestamp(value).strftime("%Y-%m-%d"))
        rows.append([str(index)] + values)
    return rows


conference_columns = [
    "股票代號", "公司名稱", "法說會日期", "時間", "地點", "摘要",
    "公司網站資訊", "影音連結", "其他事項", "市場別",
]
conference_matrix = [conference_columns]
for _, row in conference_combined.iterrows():
    conference_matrix.append([
        clean_text(row["symbol"]),
        clean_text(row["公司名稱"]),
        pd.Timestamp(row["date"]).strftime("%Y-%m-%d"),
        clean_text(row["召開法人說明會時間"]),
        clean_text(row["召開法人說明會地點"]),
        clean_text(row["法人說明會擇要訊息"]),
        clean_text(row["公司網站是否提供法人說明會相關資訊"]),
        clean_text(row["影音連結資訊"]),
        clean_text(row["其他應敘明事項"]),
        clean_text(row["市場別"]),
    ])

OUT_DIR.mkdir(parents=True, exist_ok=True)
revenue_combined.to_parquet(OUT_DIR / "monthly_revenue_combined.parquet")
revenue_last_combined.to_parquet(OUT_DIR / "monthly_revenue_last_year_combined.parquet")
eps_combined.to_parquet(OUT_DIR / "eps_combined.parquet")
volume_combined.to_parquet(OUT_DIR / "volume_shares_combined.parquet")
conference_combined.to_parquet(OUT_DIR / "investor_conferences_combined.parquet", index=False)

manifest = {
    "created_at": date.today().isoformat(),
    "companies": len(symbols),
    "updated": {
        "monthly_revenue": [revenue_combined.index.min().strftime("%Y-%m"), revenue_combined.index.max().strftime("%Y-%m")],
        "eps": [str(eps_combined.index.min()), str(eps_combined.index.max())],
        "volume": [volume_combined.index.min().strftime("%Y-%m-%d"), volume_combined.index.max().strftime("%Y-%m-%d")],
        "conference": [conference_combined["date"].min().strftime("%Y-%m-%d"), conference_combined["date"].max().strftime("%Y-%m-%d")],
    },
    "checks": {
        "revenue_overlap_comparisons": revenue_comparisons,
        "revenue_overlap_mismatches": revenue_mismatches,
        "eps_overlap_comparisons": eps_comparisons,
        "eps_overlap_mismatches_tolerance_0_011": eps_mismatches,
        "volume_overlap_comparisons": volume_comparisons,
        "volume_overlap_mismatches": volume_mismatches,
    },
    "failures": {
        "revenue": revenue_failures,
        "eps": eps_failures,
        "volume": volume_failures,
        "conference": conference_failures,
    },
    "not_updated": {
        "market_value": "FinMind TaiwanStockMarketValue requires Backer; no free exact daily replacement used.",
        "financial_statement_disclosure_dates": "MOPS upload dates require separate per-filing extraction; retained FinLab through 2023Q4.",
    },
}
(OUT_DIR / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

payload = {
    "meta": manifest,
    "sources": {
        "overview": "資料來源：FinLab（原始期間）；MOPS、FinMind、Yahoo Finance（2024 年後補充）。",
        "monthly_revenue": "資料來源：2019-09～2023-11 FinLab monthly_revenue:當月營收；2023-12 起 MOPS 月營收歷史檔（https://mopsov.twse.com.tw/nas/t21/）。單位：新台幣千元。",
        "monthly_revenue_last_year": "資料來源：2019-09～2023-11 FinLab monthly_revenue:去年當月營收；2023-12 起 MOPS 月營收歷史檔（https://mopsov.twse.com.tw/nas/t21/）。單位：新台幣千元。",
        "eps": "資料來源：2019Q4～2023Q3 FinLab financial_statement:每股盈餘；2023Q4 起 FinMind TaiwanStockFinancialStatements（https://api.finmindtrade.com/api/v4/data），篩選 type=EPS。",
        "volume": "資料來源：2019-10～2023-12 FinLab price:成交股數；2024 起 Yahoo Finance chart API（https://query1.finance.yahoo.com/v8/finance/chart/）。單位：股。",
        "market_value": "資料來源：FinLab etl:market_value，資料至 2023-12-29。2024 年後尚未補：免費來源無可直接取得的精確每日個股市值，未使用估算值。",
        "disclosure": "資料來源：FinLab etl:financial_statements_disclosure_dates，資料至 2023Q4。2024 年後尚未補：MOPS 電子文件上傳日期需另行逐檔擷取。",
        "conference": "資料來源：2019-10～2023-12 FinLab investors_conference；2024 起 MOPS 法人說明會一覽表（https://mopsov.twse.com.tw/mops/web/t100sb02_1）。",
    },
    "monthly_revenue": matrix_from_wide(revenue_combined, "資料月份", date_index=True, number_decimals=0),
    "monthly_revenue_last_year": matrix_from_wide(revenue_last_combined, "資料月份", date_index=True, number_decimals=0),
    "eps": matrix_from_wide(eps_combined, "財務季度"),
    "volume": matrix_from_wide(volume_combined, "日期", date_index=True, number_decimals=0),
    "market_value": matrix_from_wide(market_value, "日期", date_index=True, number_decimals=0),
    "disclosure": matrix_from_disclosure(disclosure),
    "conference": conference_matrix,
}
INPUT_JSON.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
print(json.dumps(manifest, ensure_ascii=False, indent=2), flush=True)
print(INPUT_JSON, flush=True)
