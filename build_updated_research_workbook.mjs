import fs from "node:fs/promises";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const input = JSON.parse(await fs.readFile("research_updates_input.json", "utf8"));
const outputDir = "../../outputs/public_research_updates";
const outputPath = `${outputDir}/finlab_research_data_2024_plus.xlsx`;
const fontFamily = "Arial";
const titleColor = "#1F2937";
const headerColor = "#1F4E78";
const sourceColor = "#1D4ED8";
const noteColor = "#475569";
const warningColor = "#9A3412";

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

function writeSourceRow(sheet, source, mergeEndColumn = "L") {
  sheet.mergeCells(`A1:${mergeEndColumn}1`);
  sheet.getRange("A1").values = [[source]];
  sheet.getRange(`A1:${mergeEndColumn}1`).format = {
    fill: "#EFF6FF",
    font: { name: fontFamily, size: 9, italic: true, color: sourceColor },
    verticalAlignment: "center",
    wrapText: true,
  };
  sheet.getRange("1:1").format.rowHeight = 38;
}

function styleDataTable(sheet, matrix, options = {}) {
  const rows = matrix.length;
  const cols = matrix[0].length;
  const range = sheet.getRangeByIndexes(1, 0, rows, cols);
  range.format.font = { name: fontFamily, size: 10, color: titleColor };
  range.format.verticalAlignment = "center";
  const header = sheet.getRangeByIndexes(1, 0, 1, cols);
  header.format = {
    fill: headerColor,
    font: { name: fontFamily, size: 10, bold: true, color: "#FFFFFF" },
    horizontalAlignment: "center",
    verticalAlignment: "center",
    borders: { preset: "outside", style: "thin", color: headerColor },
  };
  header.format.rowHeight = 26;
  sheet.getRangeByIndexes(1, 0, rows, 1).format.columnWidth = options.firstWidth ?? 14;
  if (cols > 1) {
    sheet.getRangeByIndexes(1, 1, rows, cols - 1).format.columnWidth = options.dataWidth ?? 13;
  }
  if (options.firstColumnDates && rows > 1) {
    sheet.getRangeByIndexes(2, 0, rows - 1, 1).setNumberFormat("yyyy-mm-dd");
  }
  if (options.allDataDates && rows > 1 && cols > 1) {
    sheet.getRangeByIndexes(2, 1, rows - 1, cols - 1).setNumberFormat("yyyy-mm-dd");
  }
  if (options.numberFormat && rows > 1 && cols > 1) {
    sheet.getRangeByIndexes(2, 1, rows - 1, cols - 1).setNumberFormat(options.numberFormat);
  }
  sheet.freezePanes.freezeRows(2);
  sheet.freezePanes.freezeColumns(1);
  sheet.showGridLines = false;
  sheet.tabColor = headerColor;
}

function addWideSheet(workbook, name, matrix, source, options) {
  const sheet = workbook.worksheets.add(name);
  writeSourceRow(sheet, source);
  const parsed = parseDates(matrix, options.dateMode ?? "none");
  sheet.getRangeByIndexes(1, 0, parsed.length, parsed[0].length).values = parsed;
  styleDataTable(sheet, parsed, options);
  return sheet;
}

const workbook = Workbook.create();
const meta = input.meta;

const overview = workbook.worksheets.add("資料說明");
writeSourceRow(
  overview,
  "資料來源：FinLab（原始期間）；MOPS、FinMind、臺灣證券交易所（TWSE）與櫃買中心（TPEx）（2024 年後補充）。",
  "F",
);
overview.getRange("A3").values = [["FinLab 研究資料（公開資料補充版）"]];
overview.getRange("A3").format.font = { name: fontFamily, size: 15, bold: true, color: titleColor };
overview.getRange("A4").values = [[`研究範圍：${meta.companies} 家半導體公司；建立日期：${meta.created_at}。缺值保留空白，不以 0 取代。`]];
overview.getRange("A4").format.font = { name: fontFamily, size: 10, italic: true, color: noteColor };
overview.getRange("A6:F6").values = [["工作表", "資料內容", "單位", "期間／筆數", "更新狀態", "補充來源"]];
overview.getRange("A7:F13").values = [
  ["月營收", "179 家公司的當月營收", "新台幣千元", `${meta.updated.monthly_revenue[0]} 至 ${meta.updated.monthly_revenue[1]}；${input.monthly_revenue.length - 1} 月`, "已補至最新完整月份", "MOPS"],
  ["去年同期營收", "179 家公司的去年同月營收", "新台幣千元", `${meta.updated.monthly_revenue[0]} 至 ${meta.updated.monthly_revenue[1]}；${input.monthly_revenue_last_year.length - 1} 月`, "已補至最新完整月份", "MOPS"],
  ["EPS", "季度每股盈餘", "新台幣元／股", `${meta.updated.eps[0]} 至 ${meta.updated.eps[1]}；${input.eps.length - 1} 季`, "已補；重疊檢查 2 筆小幅差異", "FinMind"],
  ["成交量", "每日成交股數", "股", `${meta.updated.volume[0]} 至 ${meta.updated.volume[1]}；${input.volume.length - 1} 日`, "已補；官方交易所資料", "TWSE／TPEx"],
  ["市值", "每日公司市值", "新台幣元", `資料至 2023-12-29；${input.market_value.length - 1} 日`, "2024 年後尚未補", "保留 FinLab 原值"],
  ["財報揭露日", "各季財務報表揭露日期", "日期", `資料至 2023Q4；${input.disclosure.length - 1} 季`, "2024 年後尚未補", "保留 FinLab 原值"],
  ["法說會", "日期、時間、地點與摘要", "事件紀錄", `${meta.updated.conference[0]} 至 ${meta.updated.conference[1]}；${input.conference.length - 1} 筆`, "已補至 MOPS 可查日期", "MOPS"],
];
overview.getRange("A6:F13").format.font = { name: fontFamily, size: 10, color: titleColor };
overview.getRange("A6:F6").format = {
  fill: headerColor,
  font: { name: fontFamily, size: 10, bold: true, color: "#FFFFFF" },
  horizontalAlignment: "center",
  verticalAlignment: "center",
};
overview.getRange("A7:F13").format.verticalAlignment = "center";
overview.getRange("E11:E12").format.font = { name: fontFamily, size: 10, bold: true, color: warningColor };
overview.getRange("A6:A13").format.columnWidth = 17;
overview.getRange("B6:B13").format.columnWidth = 34;
overview.getRange("C6:C13").format.columnWidth = 17;
overview.getRange("D6:D13").format.columnWidth = 34;
overview.getRange("E6:E13").format.columnWidth = 30;
overview.getRange("F6:F13").format.columnWidth = 22;
overview.getRange("A15").values = [[`品質檢查：營收重疊 ${meta.checks.revenue_overlap_comparisons} 筆、差異 ${meta.checks.revenue_overlap_mismatches} 筆；成交量重疊 ${meta.checks.volume_overlap_comparisons} 筆、差異 ${meta.checks.volume_overlap_mismatches} 筆。`]];
overview.getRange("A15").format.font = { name: fontFamily, size: 10, italic: true, color: noteColor };
overview.showGridLines = false;
overview.freezePanes.freezeRows(1);
overview.tabColor = headerColor;

addWideSheet(workbook, "月營收", input.monthly_revenue, input.sources.monthly_revenue, {
  dateMode: "firstColumn", firstColumnDates: true, numberFormat: "#,##0", dataWidth: 14,
});
addWideSheet(workbook, "去年同期營收", input.monthly_revenue_last_year, input.sources.monthly_revenue_last_year, {
  dateMode: "firstColumn", firstColumnDates: true, numberFormat: "#,##0", dataWidth: 14,
});
addWideSheet(workbook, "EPS", input.eps, input.sources.eps, {
  numberFormat: "0.00", firstWidth: 13, dataWidth: 12,
});
addWideSheet(workbook, "成交量", input.volume, input.sources.volume, {
  dateMode: "firstColumn", firstColumnDates: true, numberFormat: "#,##0", dataWidth: 14,
});
addWideSheet(workbook, "市值", input.market_value, input.sources.market_value, {
  dateMode: "firstColumn", firstColumnDates: true, numberFormat: "#,##0", dataWidth: 18,
});
addWideSheet(workbook, "財報揭露日", input.disclosure, input.sources.disclosure, {
  dateMode: "allDataCells", allDataDates: true, firstWidth: 13, dataWidth: 14,
});

const conference = workbook.worksheets.add("法說會");
writeSourceRow(conference, input.sources.conference, "J");
const conferenceMatrix = parseDates(input.conference, "conferenceDate");
conference.getRangeByIndexes(1, 0, conferenceMatrix.length, conferenceMatrix[0].length).values = conferenceMatrix;
styleDataTable(conference, conferenceMatrix, { firstWidth: 12, dataWidth: 18 });
conference.getRangeByIndexes(2, 2, conferenceMatrix.length - 1, 1).setNumberFormat("yyyy-mm-dd");
conference.getRange("A:A").format.columnWidth = 12;
conference.getRange("B:B").format.columnWidth = 18;
conference.getRange("C:C").format.columnWidth = 14;
conference.getRange("D:D").format.columnWidth = 12;
conference.getRange("E:E").format.columnWidth = 38;
conference.getRange("F:F").format.columnWidth = 58;
conference.getRange("G:G").format.columnWidth = 20;
conference.getRange("H:H").format.columnWidth = 50;
conference.getRange("I:I").format.columnWidth = 35;
conference.getRange("J:J").format.columnWidth = 10;
conference.getRangeByIndexes(2, 4, conferenceMatrix.length - 1, 5).format.wrapText = true;
conference.getRangeByIndexes(2, 0, conferenceMatrix.length - 1, 10).format.rowHeight = 42;
conference.getRangeByIndexes(2, 4, conferenceMatrix.length - 1, 5).format.verticalAlignment = "top";

workbook.recalculate();

for (const [sheetName, range] of [
  ["資料說明", "A1:F15"], ["月營收", "A1:H8"], ["去年同期營收", "A1:H8"],
  ["EPS", "A1:H8"], ["成交量", "A1:H8"], ["市值", "A1:H8"],
  ["財報揭露日", "A1:H8"], ["法說會", "A1:J8"],
]) {
  const check = await workbook.inspect({
    kind: "table", range: `${sheetName}!${range}`, include: "values,formulas",
    tableMaxRows: 16, tableMaxCols: 10, maxChars: 12000,
  });
  console.log(check.ndjson);
}

const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!",
  options: { useRegex: true, maxResults: 300 },
  summary: "final formula error scan",
});
console.log(errors.ndjson);

await fs.mkdir(outputDir, { recursive: true });
const previewSpecs = [
  ["資料說明", "A1:F15", "preview_updated_01_overview.png"],
  ["月營收", "A1:L10", "preview_updated_02_revenue.png"],
  ["去年同期營收", "A1:L10", "preview_updated_03_revenue_last_year.png"],
  ["EPS", "A1:L10", "preview_updated_04_eps.png"],
  ["成交量", "A1:L10", "preview_updated_05_volume.png"],
  ["市值", "A1:L10", "preview_updated_06_market_value.png"],
  ["財報揭露日", "A1:L10", "preview_updated_07_disclosure.png"],
  ["法說會", "A1:J10", "preview_updated_08_conference.png"],
];
for (const [sheetName, range, filename] of previewSpecs) {
  const preview = await workbook.render({ sheetName, range, scale: 1.15, format: "png" });
  await fs.writeFile(filename, new Uint8Array(await preview.arrayBuffer()));
}

const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
console.log(JSON.stringify({ output: outputPath, sheets: previewSpecs.map((item) => item[0]) }));
