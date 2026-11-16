import fs from "node:fs/promises";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const input = JSON.parse(await fs.readFile("research_input.json", "utf8"));
const outputDir = "../../outputs/finlab_research_workbook";
const outputPath = `${outputDir}/finlab_research_data.xlsx`;
const fontFamily = "Arial";
const titleColor = "#1F2937";
const headerColor = "#1F4E78";
const noteColor = "#475569";

function isIsoDate(value) {
  return typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value);
}

function parseDates(matrix, mode) {
  return matrix.map((row, rowIndex) => row.map((value, colIndex) => {
    if (rowIndex === 0) return value;
    if (mode === "firstColumn" && colIndex === 0 && isIsoDate(value)) {
      return new Date(`${value}T00:00:00`);
    }
    if (mode === "allDataCells" && colIndex > 0 && isIsoDate(value)) {
      return new Date(`${value}T00:00:00`);
    }
    if (mode === "conferenceDate" && colIndex === 2 && isIsoDate(value)) {
      return new Date(`${value}T00:00:00`);
    }
    return value;
  }));
}

function styleDataTable(sheet, matrix, options = {}) {
  const rows = matrix.length;
  const cols = matrix[0].length;
  const range = sheet.getRangeByIndexes(0, 0, rows, cols);
  range.format.font = { name: fontFamily, size: 10, color: titleColor };
  range.format.verticalAlignment = "center";
  const header = sheet.getRangeByIndexes(0, 0, 1, cols);
  header.format = {
    fill: headerColor,
    font: { name: fontFamily, size: 10, bold: true, color: "#FFFFFF" },
    horizontalAlignment: "center",
    verticalAlignment: "center",
    borders: { preset: "outside", style: "thin", color: headerColor },
  };
  header.format.rowHeight = 26;
  sheet.getRangeByIndexes(0, 0, rows, 1).format.columnWidth = options.firstWidth ?? 14;
  if (cols > 1) {
    sheet.getRangeByIndexes(0, 1, rows, cols - 1).format.columnWidth = options.dataWidth ?? 13;
  }
  if (options.firstColumnDates && rows > 1) {
    sheet.getRangeByIndexes(1, 0, rows - 1, 1).setNumberFormat("yyyy-mm-dd");
  }
  if (options.allDataDates && rows > 1 && cols > 1) {
    sheet.getRangeByIndexes(1, 1, rows - 1, cols - 1).setNumberFormat("yyyy-mm-dd");
  }
  if (options.numberFormat && rows > 1 && cols > 1) {
    sheet.getRangeByIndexes(1, 1, rows - 1, cols - 1).setNumberFormat(options.numberFormat);
  }
  sheet.freezePanes.freezeRows(1);
  sheet.freezePanes.freezeColumns(1);
  sheet.showGridLines = false;
}

function addWideSheet(workbook, name, dataset, options) {
  const sheet = workbook.worksheets.add(name);
  const matrix = parseDates(dataset.matrix, options.dateMode ?? "none");
  sheet.getRangeByIndexes(0, 0, matrix.length, matrix[0].length).values = matrix;
  styleDataTable(sheet, matrix, options);
  return sheet;
}

const workbook = Workbook.create();

const overview = workbook.worksheets.add("資料說明");
overview.getRange("A2").values = [["FinLab 研究資料"]];
overview.getRange("A2").format.font = { name: fontFamily, size: 14, bold: true, color: titleColor };
overview.getRange("A3").values = [["半導體公司營收、EPS、交易與事件資料。FinLab 免費方案資料目前下載至 2023 年底。"]];
overview.getRange("A3").format.font = { name: fontFamily, size: 10, italic: true, color: noteColor };
overview.getRange("A5:E5").values = [["工作表", "資料內容", "單位", "筆數／期間", "FinLab 來源鍵"]];
overview.getRange("A6:E12").values = [
  ["月營收", "179 家公司的當月營收", "新台幣千元", "51 個公告日；2019-10 至 2023-12", "monthly_revenue:當月營收"],
  ["去年同期營收", "179 家公司的去年同月營收", "新台幣千元", "51 個公告日；2019-10 至 2023-12", "monthly_revenue:去年當月營收"],
  ["EPS", "季度每股盈餘", "新台幣元／股", "16 季；2019Q4 至 2023Q3", "financial_statement:每股盈餘"],
  ["成交量", "每日成交股數", "股", "1,038 個交易日；2019-10 至 2023-12", "price:成交股數"],
  ["市值", "每日公司市值", "新台幣元", "1,112 列；2019-10 至 2023-12", "etl:market_value"],
  ["財報揭露日", "各季財務報表揭露日期", "日期", "17 季；2019Q4 至 2023Q4", "etl:financial_statements_disclosure_dates"],
  ["法說會", "法人說明會日期、時間、地點與摘要", "事件紀錄", `${input.conference.rows.toLocaleString()} 筆`, "investors_conference"],
];
overview.getRange("A5:E12").format.font = { name: fontFamily, size: 10, color: titleColor };
overview.getRange("A5:E5").format = {
  fill: headerColor,
  font: { name: fontFamily, size: 10, bold: true, color: "#FFFFFF" },
  horizontalAlignment: "center",
  verticalAlignment: "center",
};
overview.getRange("A5:E12").format.verticalAlignment = "center";
overview.getRange("A6:B12").format.horizontalAlignment = "left";
overview.getRange("C6:D12").format.horizontalAlignment = "center";
overview.getRange("E6:E12").format.horizontalAlignment = "left";
overview.getRange("A5:A12").format.columnWidth = 16;
overview.getRange("B5:B12").format.columnWidth = 35;
overview.getRange("C5:C12").format.columnWidth = 18;
overview.getRange("D5:D12").format.columnWidth = 30;
overview.getRange("E5:E12").format.columnWidth = 44;
overview.getRange("A14").values = [["缺值代表該公司在該日期沒有可用紀錄，未以 0 取代。股票代號保留為文字。"]];
overview.getRange("A14").format.font = { name: fontFamily, size: 10, italic: true, color: noteColor };
overview.showGridLines = false;
overview.tabColor = headerColor;

addWideSheet(workbook, "月營收", input.datasets.monthly_revenue, {
  dateMode: "firstColumn", firstColumnDates: true, numberFormat: "#,##0", dataWidth: 14,
});
addWideSheet(workbook, "去年同期營收", input.datasets.monthly_revenue_last_year, {
  dateMode: "firstColumn", firstColumnDates: true, numberFormat: "#,##0", dataWidth: 14,
});
addWideSheet(workbook, "EPS", input.datasets.eps, {
  numberFormat: "0.00", firstWidth: 13, dataWidth: 12,
});
addWideSheet(workbook, "成交量", input.datasets.volume, {
  dateMode: "firstColumn", firstColumnDates: true, numberFormat: "#,##0", dataWidth: 14,
});
addWideSheet(workbook, "市值", input.datasets.market_value, {
  dateMode: "firstColumn", firstColumnDates: true, numberFormat: "#,##0", dataWidth: 18,
});
addWideSheet(workbook, "財報揭露日", input.datasets.disclosure, {
  dateMode: "allDataCells", allDataDates: true, firstWidth: 13, dataWidth: 14,
});

const conference = workbook.worksheets.add("法說會");
const conferenceMatrix = parseDates(input.conference.matrix, "conferenceDate");
conference.getRangeByIndexes(0, 0, conferenceMatrix.length, conferenceMatrix[0].length).values = conferenceMatrix;
styleDataTable(conference, conferenceMatrix, { firstWidth: 12, dataWidth: 18 });
conference.getRangeByIndexes(1, 2, conferenceMatrix.length - 1, 1).setNumberFormat("yyyy-mm-dd");
conference.getRange("A:A").format.columnWidth = 12;
conference.getRange("B:B").format.columnWidth = 18;
conference.getRange("C:C").format.columnWidth = 14;
conference.getRange("D:D").format.columnWidth = 10;
conference.getRange("E:E").format.columnWidth = 38;
conference.getRange("F:F").format.columnWidth = 58;
conference.getRange("G:G").format.columnWidth = 20;
conference.getRange("H:H").format.columnWidth = 50;
conference.getRange("I:I").format.columnWidth = 35;
conference.getRange("J:J").format.columnWidth = 10;
conference.getRangeByIndexes(1, 0, conferenceMatrix.length - 1, 10).format.wrapText = false;

workbook.recalculate();

const overviewCheck = await workbook.inspect({
  kind: "table",
  range: "資料說明!A2:E14",
  include: "values,formulas",
  tableMaxRows: 14,
  tableMaxCols: 5,
  maxChars: 10000,
});
console.log(overviewCheck.ndjson);

const revenueCheck = await workbook.inspect({
  kind: "table",
  range: "月營收!A1:H6",
  include: "values,formulas",
  tableMaxRows: 6,
  tableMaxCols: 8,
  maxChars: 8000,
});
console.log(revenueCheck.ndjson);

const conferenceCheck = await workbook.inspect({
  kind: "table",
  range: "法說會!A1:J6",
  include: "values,formulas",
  tableMaxRows: 6,
  tableMaxCols: 10,
  maxChars: 10000,
});
console.log(conferenceCheck.ndjson);

const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!",
  options: { useRegex: true, maxResults: 300 },
  summary: "final formula error scan",
});
console.log(errors.ndjson);

await fs.mkdir(outputDir, { recursive: true });
const previewSpecs = [
  ["資料說明", "A1:E15", "preview_01_overview.png"],
  ["月營收", "A1:H12", "preview_02_revenue.png"],
  ["去年同期營收", "A1:H12", "preview_03_revenue_last_year.png"],
  ["EPS", "A1:H12", "preview_04_eps.png"],
  ["成交量", "A1:H12", "preview_05_volume.png"],
  ["市值", "A1:H12", "preview_06_market_value.png"],
  ["財報揭露日", "A1:H12", "preview_07_disclosure.png"],
  ["法說會", "A1:J12", "preview_08_conference.png"],
];
for (const [sheetName, range, filename] of previewSpecs) {
  const preview = await workbook.render({ sheetName, range, scale: 1.2, format: "png" });
  await fs.writeFile(filename, new Uint8Array(await preview.arrayBuffer()));
}

const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
console.log(JSON.stringify({ output: outputPath, sheets: previewSpecs.map((item) => item[0]) }));
