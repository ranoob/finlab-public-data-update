import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data" / "finlab_research"
OUTPUT = Path(__file__).resolve().parent / "research_input.json"


def clean_value(value):
    if pd.isna(value):
        return None
    if isinstance(value, str) and value.strip().lower() == "nan":
        return None
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, (int, float, str, bool)) or value is None:
        return value
    return str(value)


master = pd.read_parquet(DATA_DIR / "company_master.parquet")
name_by_symbol = {
    str(row["symbol"]): str(row["公司簡稱"])
    for _, row in master.iterrows()
}


def wide_matrix(path, index_label):
    frame = pd.read_parquet(DATA_DIR / path)
    header = [index_label] + [
        f"{symbol} {name_by_symbol.get(str(symbol), '')}".strip()
        for symbol in frame.columns
    ]
    rows = [header]
    for index, row in frame.iterrows():
        if isinstance(index, pd.Timestamp):
            index_value = index.strftime("%Y-%m-%d")
        else:
            index_value = str(index)
        rows.append([index_value] + [clean_value(value) for value in row.tolist()])
    return {
        "matrix": rows,
        "rows": len(frame),
        "companies": len(frame.columns),
        "first": str(frame.index.min()),
        "last": str(frame.index.max()),
    }


datasets = {
    "monthly_revenue": wide_matrix("monthly/monthly_revenue.parquet", "公告日期"),
    "monthly_revenue_last_year": wide_matrix(
        "monthly/monthly_revenue_last_year.parquet", "公告日期"
    ),
    "eps": wide_matrix("quarterly/eps.parquet", "財務季度"),
    "volume": wide_matrix("daily/volume_shares.parquet", "日期"),
    "market_value": wide_matrix("daily/market_value_twd.parquet", "日期"),
    "disclosure": wide_matrix(
        "events/financial_statement_disclosure_dates.parquet", "財務季度"
    ),
}

conference = pd.read_parquet(DATA_DIR / "events/investor_conferences.parquet")
conference_columns = [
    ("symbol", "股票代號"),
    ("公司名稱", "公司名稱"),
    ("date", "法說會日期"),
    ("召開法人說明會時間", "時間"),
    ("召開法人說明會地點", "地點"),
    ("法人說明會擇要訊息", "摘要"),
    ("公司網站是否提供法人說明會相關資訊", "公司網站資訊"),
    ("影音連結資訊(國內自辦應揭露，受邀參加可自願揭露)", "影音連結"),
    ("其他應敘明事項", "其他事項"),
    ("市場別", "市場別"),
]
conference_matrix = [[label for _, label in conference_columns]]
for _, row in conference.iterrows():
    conference_matrix.append(
        [clean_value(row[source]) for source, _ in conference_columns]
    )

result = {
    "meta": {
        "created_at": "2026-11-10",
        "company_count": 179,
        "free_plan_limit": "FinLab 免費方案目前下載至 2023 年底",
    },
    "datasets": datasets,
    "conference": {
        "matrix": conference_matrix,
        "rows": len(conference),
        "first": str(conference["date"].min()),
        "last": str(conference["date"].max()),
    },
}

OUTPUT.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
print(OUTPUT)
