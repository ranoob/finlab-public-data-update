import fs from "node:fs/promises";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const input = JSON.parse(await fs.readFile("public_close_input.json", "utf8"));
const outputDir = "../../outputs/public_stock_price";
const outputPath = `${outputDir}/stock_close_2019_2026.xlsx`;
const fontFamily = "Arial";
const headerColor = "#1F4E78";
const textColor = "#1F2937";
const noteColor = "#475569";

function convertDates(matrix) {
  return matrix.map((row, index) => {
    if (index === 0) return row;
    const next = [...row];
    next[0] = new Date(`${next[0]}T00:00:00`);
    return next;
  });
}

function styleDataSheet(sheet, matrix, startRow) {
  const rowCount = matrix.length;
  const colCount = matrix[0].length;
  const whole = sheet.getRangeByIndexes(startRow, 0, rowCount, colCount);
  whole.format.font = { name: fontFamily, size: 10, color: textColor };
  whole.format.verticalAlignment = "center";

  const header = sheet.getRangeByIndexes(startRow, 0, 1, colCount);
  header.format = {
    fill: headerColor,
    font: { name: fontFamily, size: 10, bold: true, color: "#FFFFFF" },
    horizontalAlignment: "center",
    verticalAlignment: "center",
    borders: { preset: "outside", style: "thin", color: headerColor },
  };
  header.format.rowHeight = 24;

  const dataRows = rowCount - 1;
  if (dataRows > 0) {
    sheet.getRangeByIndexes(startRow + 1, 0, dataRows, 1).setNumberFormat("yyyy-mm-dd");
    sheet.getRangeByIndexes(startRow + 1, 1, dataRows, colCount - 1).setNumberFormat("0.00");
  }
  sheet.getRangeByIndexes(startRow, 0, rowCount, 1).format.columnWidth = 13;
  if (colCount > 1) {
    sheet.getRangeByIndexes(startRow, 1, rowCount, colCount - 1).format.columnWidth = 11;
  }
  sheet.showGridLines = false;
}

const workbook = Workbook.create();

const memory = workbook.worksheets.add("記憶體樣本");
memory.getRange("A2").values = [["每日收盤價（公開資料補齊版）"]];
memory.getRange("A2").format.font = { name: fontFamily, size: 14, bold: true, color: textColor };
memory.getRange("A3").values = [[
  `記憶體樣本 13 家，${input.meta.combined_period[0]} 至 ${input.meta.combined_period[1]}。`,
]];
memory.getRange("A4").values = [[
  `原始資料：FinLab price:收盤價（${input.meta.original_period[0]} 至 ${input.meta.original_period[1]}）。`,
]];
memory.getRange("A5").values = [[
  `補充資料：FinMind TaiwanStockPrice 公開 API（${input.meta.public_period[0]} 至 ${input.meta.public_period[1]}）。`,
]];
memory.getRange("A6").values = [[
  `品質檢查：2023 年重疊區間比對 ${input.meta.overlap_comparisons.toLocaleString()} 格，差異 ${input.meta.overlap_mismatches}；179 家公司下載失敗 0。`,
]];
memory.getRange("A3:A6").format.font = { name: fontFamily, size: 10, italic: true, color: noteColor };

const memoryMatrix = convertDates(input.memory);
memory.getRangeByIndexes(7, 0, memoryMatrix.length, memoryMatrix[0].length).values = memoryMatrix;
styleDataSheet(memory, memoryMatrix, 7);
memory.freezePanes.freezeRows(8);
memory.freezePanes.freezeColumns(1);
memory.tabColor = headerColor;

const all = workbook.worksheets.add("全部半導體");
const allMatrix = convertDates(input.all);
all.getRangeByIndexes(0, 0, allMatrix.length, allMatrix[0].length).values = allMatrix;
styleDataSheet(all, allMatrix, 0);
all.freezePanes.freezeRows(1);
all.freezePanes.freezeColumns(1);

workbook.recalculate();

const memoryStart = await workbook.inspect({
  kind: "table",
  range: "記憶體樣本!A2:N14",
  include: "values,formulas",
  tableMaxRows: 13,
  tableMaxCols: 14,
  maxChars: 12000,
});
console.log(memoryStart.ndjson);

const lastRow = input.all.length;
const allEnd = await workbook.inspect({
  kind: "table",
  range: `全部半導體!A${lastRow - 3}:H${lastRow}`,
  include: "values,formulas",
  tableMaxRows: 4,
  tableMaxCols: 8,
  maxChars: 6000,
});
console.log(allEnd.ndjson);

const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!",
  options: { useRegex: true, maxResults: 300 },
  summary: "final formula error scan",
});
console.log(errors.ndjson);

await fs.mkdir(outputDir, { recursive: true });
const memoryPreview = await workbook.render({
  sheetName: "記憶體樣本",
  range: "A1:N20",
  scale: 1.35,
  format: "png",
});
await fs.writeFile("preview_public_memory.png", new Uint8Array(await memoryPreview.arrayBuffer()));

const allPreview = await workbook.render({
  sheetName: "全部半導體",
  range: "A1:H15",
  scale: 1.35,
  format: "png",
});
await fs.writeFile("preview_public_all.png", new Uint8Array(await allPreview.arrayBuffer()));

const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
console.log(JSON.stringify({
  output: outputPath,
  companies: input.meta.companies,
  publicPeriod: input.meta.public_period,
  combinedPeriod: input.meta.combined_period,
  overlapMismatches: input.meta.overlap_mismatches,
}));
