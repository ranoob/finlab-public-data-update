# FinLab semiconductor research data (2024+ update)

This private research repository contains the project code, public-source data updates, and Excel deliverables for a Taiwan semiconductor-company dataset.

## Repository contents

- `code/`: initial FinLab extraction and test scripts.
- `scripts/`: scripts for public-data collection, validation, and Excel generation.
- `data/public_research_updates/`: combined monthly revenue, EPS, trading volume, and investor-conference datasets.
- `data/public_stock_price/`: public close-price extension datasets.
- `outputs/`: final Excel workbooks.

## Data coverage

- Monthly revenue and prior-year monthly revenue: through 2026-10.
- EPS: through 2026Q3.
- Daily trading volume: through 2026-11-10.
- Investor conferences: MOPS records available through 2026-11-27.
- Close prices: through 2026-11-10.
- Market value remains through 2023-12-29.
- Financial-statement disclosure dates remain through 2023Q4.

## Sources

- FinLab: original historical dataset through 2023.
- MOPS: monthly revenue and investor-conference records.
- FinMind: EPS and close-price extensions.
- Taiwan Stock Exchange (TWSE) and Taipei Exchange (TPEx): official daily trading volume.

Every worksheet in the final research workbook includes its data source in the first row. The workbook's `資料說明` sheet lists coverage and known limitations.

## Run locally

1. Create a Python virtual environment.
2. Install dependencies from `requirements.txt`.
3. Add FinLab credentials locally when running the original FinLab extraction. Never commit credentials or tokens.
4. Run the collection scripts from the repository root.

The Excel builder scripts use OpenAI's local artifact runtime in the original workspace. The generated Excel files are included in `outputs/` for direct use.

