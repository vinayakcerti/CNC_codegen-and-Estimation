// Round-trip test for src/excelExport.ts (ARD R1 workbook builder).
//
// Builds a sample payload (2 machined parts with 3 ops / 2 holes / 2
// features each + 1 purchased part; cost library with confirmed and
// unconfirmed rows), calls buildWorkbook, writes the Blob to a temp file,
// re-reads it with exceljs, and asserts the ARD workbook contract:
// sheet count + sanitized/deduped names, Summary rows, TOTAL row math,
// reconciliation line, purchased-part handling, orange fill on the
// unconfirmed library row, bold frozen headers, and number formats.
//
// Run from frontend/:  node scripts/test_excel.mjs
// (Node >= 23.6 strips types from the imported .ts natively; on older
// Node use: npx tsx scripts/test_excel.mjs)

import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import ExcelJS from "exceljs";
import { buildWorkbook } from "../src/excelExport.ts";

// ---- tiny assert harness ------------------------------------------------
let failures = 0;
function check(desc, ok, detail = "") {
  if (ok) {
    console.log(`PASS: ${desc}`);
  } else {
    failures++;
    console.log(`FAIL: ${desc}${detail ? ` — ${detail}` : ""}`);
  }
}
const close = (a, b) => typeof a === "number" && Math.abs(a - b) < 1e-9;

// ---- sample payload -------------------------------------------------------
// Part names deliberately exercise the sheet-name rules:
//  - parts 1+2 share a >31-char prefix -> truncation + " (2)" dedupe
//  - part 3 contains []:/ illegal characters -> sanitized to _
const payload = {
  filename: "quote_export_test.xlsx",
  currencySymbol: "₹",
  costingModel: "ratecard",
  library: [
    {
      category: "Machining",
      sub: "VMC 3-axis",
      unit: "hr",
      rate: 850,
      effectiveFrom: "2026-04-01",
      source: "Vendor RFQ",
      confirmed: true,
    },
    {
      category: "Machining",
      sub: "Drilling per hole",
      unit: "hole",
      rate: 12.5,
      effectiveFrom: "2026-05-15",
      source: "Heuristic seed",
      confirmed: false, // -> ORANGE row
    },
    {
      category: "Finishing",
      sub: "Anodize clear",
      unit: "m²",
      rate: 450,
      effectiveFrom: "2026-06-01",
      source: "Catalog",
      confirmed: true,
    },
  ],
  parts: [
    {
      name: "Hydraulic Manifold Block Assembly A",
      bodyIndex: 0,
      material: "AL6061-T6",
      quantity: 2,
      weightKg: 1.85,
      machinedAreaCm2: 145.5,
      holeCount: 2,
      addons: ["anodize", "deburr"],
      costInr: 1250.5,
      cycleMin: 42.25,
      ops: [
        { opNum: 1, setup: "Setup 1 (Top)", opType: "Face mill", tool: "Ø50 face mill", feature: "Top face", depthMm: 1.5, cutLenMm: 320, cycleMin: 4.5, areaCm2: 145.5, costInr: 95.25 },
        { opNum: 2, setup: "Setup 1 (Top)", opType: "Drill", tool: "Ø8.5 drill", feature: "Hole H1", depthMm: 25, cutLenMm: 25, cycleMin: 1.2, areaCm2: 6.7, costInr: 12.5 },
        { opNum: 3, setup: "Setup 2 (Bottom)", opType: "Pocket", tool: "Ø12 endmill", feature: "Pocket P1", depthMm: 10, cutLenMm: 850, cycleMin: 12.75, areaCm2: 38.2, costInr: null, costNote: "rate pending" },
      ],
      holes: [
        { id: "H1", diaMm: 8.5, tolerance: "H7", thicknessMm: 25, thread: "M10", through: "Yes", costInr: 12.5, fallback: false },
        { id: "H2", diaMm: 5, tolerance: "±0.2", thicknessMm: 12, thread: "No Thread", through: "No", costInr: 8, fallback: false },
      ],
      features: [
        { type: "pocket", name: "Pocket P1", dia: null, l: 45, w: 30, depth: 10, confidence: "high", setup: "Setup 2 (Bottom)" },
        { type: "hole", name: "Hole H1", dia: 8.5, l: null, w: null, depth: 25, confidence: "high", setup: "Setup 1 (Top)" },
      ],
    },
    {
      name: "Hydraulic Manifold Block Assembly B",
      bodyIndex: 1,
      material: "SS304",
      quantity: 1,
      weightKg: 3.2,
      machinedAreaCm2: 89.25,
      holeCount: 2,
      addons: [],
      costInr: 2100.75,
      cycleMin: 65.5,
      ops: [
        { opNum: 1, setup: "Setup 1 (Top)", opType: "Face mill", tool: "Ø63 face mill", feature: "Top face", depthMm: 2, cutLenMm: 410, cycleMin: 6.25, areaCm2: 89.25, costInr: 140 },
        { opNum: 2, setup: "Setup 1 (Top)", opType: "Drill", tool: "Ø6.8 drill", feature: "Hole H1", depthMm: null, cutLenMm: null, cycleMin: 0.9, areaCm2: 3.1, costInr: 12.5 },
        { opNum: 3, setup: "Setup 1 (Top)", opType: "Counterbore", tool: "Ø11 counterbore", feature: "Hole H1 c'bore", depthMm: 6.5, cutLenMm: 6.5, cycleMin: 0.8, areaCm2: 1.2, costInr: 9.75 },
      ],
      holes: [
        { id: "H1", diaMm: 6.8, tolerance: "±0.1", thicknessMm: null, thread: "No Thread", through: "No", costInr: null, fallback: true, counterDiaMm: 11, counterDepthMm: 6.5 },
        { id: "H2", diaMm: 10.2, tolerance: "H8", thicknessMm: 18, thread: "M12", through: "Yes", costInr: 18.75, fallback: false },
      ],
      features: [
        { type: "hole", name: "Hole H1", dia: 6.8, l: null, w: null, depth: 20, confidence: "medium", setup: "Setup 1 (Top)" },
        { type: "slot", name: "Slot S1", dia: null, l: 60, w: 12, depth: 8, confidence: "high", setup: "Setup 1 (Top)" },
      ],
    },
    {
      // Purchased part: nonzero costInr on purpose — the Summary must force
      // it to 0 and flag it in the Add-ons column (ARD).
      name: "Purchased: Bearing/6205 [OEM]",
      bodyIndex: 2,
      material: "Steel (purchased)",
      quantity: 4,
      weightKg: null,
      machinedAreaCm2: 0,
      holeCount: 0,
      addons: [],
      costInr: 500,
      cycleMin: 0,
      purchased: true,
      ops: [],
      holes: [],
      features: [],
    },
  ],
  totals: { estimatorTotal: 3351.25 }, // 1250.50 + 2100.75 + 0 (purchased)
};

// Expected sheet names, in creation order (hand-derived from the
// sanitize/truncate/dedupe rules — 31-char cap, "_Features" reserved).
const EXPECTED_SHEETS = [
  "Summary",
  "Hydraulic Manifold Blo_Ops",
  "Hydraulic Manifold Blo_Holes",
  "Hydraulic Manifold Blo_Features",
  "Hydraulic Manifold Blo_Ops (2)",
  "Hydraulic Manifold Blo_Hole (2)",
  "Hydraulic Manifold Blo_Feat (2)",
  "Purchased_ Bearing_620_Ops",
  "Purchased_ Bearing_620_Holes",
  "Purchased_ Bearing_620_Features",
  "Cost_Library",
];

// ---- build -> temp file -> re-read ----------------------------------------
const blob = await buildWorkbook(payload);
check("buildWorkbook returned a Blob", blob instanceof Blob, `got ${Object.prototype.toString.call(blob)}`);
check("Blob has xlsx MIME type", blob.type === "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", blob.type);
check("Blob is non-empty", blob.size > 0, `size=${blob.size}`);

const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "excel-export-test-"));
const tmpFile = path.join(tmpDir, "test_output.xlsx");
fs.writeFileSync(tmpFile, Buffer.from(await blob.arrayBuffer()));
console.log(`INFO: workbook written to ${tmpFile} (${blob.size} bytes)`);

const wb = new ExcelJS.Workbook();
await wb.xlsx.readFile(tmpFile);

// ---- sheet inventory --------------------------------------------------
const names = wb.worksheets.map((ws) => ws.name);
check(`sheet count is ${EXPECTED_SHEETS.length}`, names.length === EXPECTED_SHEETS.length, `got ${names.length}: ${names.join(" | ")}`);
check(
  "sheet names match expected (sanitized, truncated, deduped, ordered)",
  JSON.stringify(names) === JSON.stringify(EXPECTED_SHEETS),
  `got ${JSON.stringify(names)}`,
);
check("all sheet names <= 31 chars", names.every((n) => n.length <= 31));
check("no sheet name contains []:*?/\\", names.every((n) => !/[[\]:*?/\\]/.test(n)));

// ---- Summary sheet ----------------------------------------------------
const summary = wb.getWorksheet("Summary");
check("Summary sheet exists", Boolean(summary));

const partRows = [2, 3, 4];
check(
  "Summary has one row per part (3 part rows)",
  partRows.every((r, i) => summary.getRow(r).getCell(1).value === payload.parts[i].name),
  partRows.map((r) => summary.getRow(r).getCell(1).value).join(" | "),
);
check("Summary TOTAL row directly follows part rows (A5)", summary.getRow(5).getCell(1).value === "TOTAL");

const costCells = partRows.map((r) => summary.getRow(r).getCell(9).value ?? 0);
const totalCost = summary.getRow(5).getCell(9).value;
const totalCycle = summary.getRow(5).getCell(10).value;
check("TOTAL cost equals sum of part cost cells", close(totalCost, costCells.reduce((a, b) => a + b, 0)), `total=${totalCost} cells=${costCells.join("+")}`);
check("TOTAL cost equals 3351.25", close(totalCost, 3351.25), `got ${totalCost}`);
check("TOTAL cycle equals 107.75", close(totalCycle, 107.75), `got ${totalCycle}`);

const purchasedRow = summary.getRow(4);
check('purchased part Add-ons cell says "purchased — not machined"', purchasedRow.getCell(8).value === "purchased — not machined", `got ${JSON.stringify(purchasedRow.getCell(8).value)}`);
check("purchased part cost forced to 0 (payload had 500)", purchasedRow.getCell(9).value === 0, `got ${purchasedRow.getCell(9).value}`);

const recon = String(summary.getRow(7).getCell(1).value ?? "");
check("reconciliation line present on Summary", recon.startsWith("Reconciliation:"), recon);
check("reconciliation compares Σ to estimator total and says OK", recon.includes("3351.25") && recon.includes("OK"), recon);

check("Summary header row is bold", summary.getRow(1).getCell(1).font?.bold === true);
check(
  "Summary header row is frozen",
  summary.views?.[0]?.state === "frozen" && summary.views?.[0]?.ySplit === 1,
  JSON.stringify(summary.views),
);
check('money cells use "#,##0.00"', summary.getRow(2).getCell(9).numFmt === "#,##0.00", `got ${JSON.stringify(summary.getRow(2).getCell(9).numFmt)}`);
check('count cells use "#,##0"', summary.getRow(2).getCell(7).numFmt === "#,##0", `got ${JSON.stringify(summary.getRow(2).getCell(7).numFmt)}`);

// ---- per-part sheets ------------------------------------------------------
const opsA = wb.getWorksheet("Hydraulic Manifold Blo_Ops");
check("part A Ops sheet has 3 op rows", opsA.rowCount === 4, `rowCount=${opsA.rowCount}`);
check("part A Ops op with null cost carries its cost note", opsA.getRow(4).getCell(11).value === "rate pending", `got ${opsA.getRow(4).getCell(11).value}`);
check("Ops header frozen+bold", opsA.views?.[0]?.state === "frozen" && opsA.getRow(1).getCell(1).font?.bold === true);

const holesB = wb.getWorksheet("Hydraulic Manifold Blo_Hole (2)");
check("part B Holes sheet has 2 hole rows", holesB.rowCount === 3, `rowCount=${holesB.rowCount}`);
check('fallback hole shows "YES" in estimated? column', holesB.getRow(2).getCell(10).value === "YES", `got ${JSON.stringify(holesB.getRow(2).getCell(10).value)}`);
check("non-fallback hole has empty estimated? cell", !holesB.getRow(3).getCell(10).value, `got ${JSON.stringify(holesB.getRow(3).getCell(10).value)}`);
check("counterbore dia/depth round-trip (11 / 6.5)", close(holesB.getRow(2).getCell(7).value, 11) && close(holesB.getRow(2).getCell(8).value, 6.5), `got ${holesB.getRow(2).getCell(7).value} / ${holesB.getRow(2).getCell(8).value}`);

const featB = wb.getWorksheet("Hydraulic Manifold Blo_Feat (2)");
check("part B Features sheet has 2 feature rows", featB.rowCount === 3, `rowCount=${featB.rowCount}`);

const opsP = wb.getWorksheet("Purchased_ Bearing_620_Ops");
check("purchased part Ops sheet exists and is empty (header only)", opsP.rowCount === 1, `rowCount=${opsP.rowCount}`);

// ---- Cost_Library sheet ----------------------------------------------
const lib = wb.getWorksheet("Cost_Library");
check("Cost_Library has 3 data rows", lib.rowCount === 4, `rowCount=${lib.rowCount}`);

const isOrange = (cell) =>
  cell.fill?.type === "pattern" && cell.fill?.fgColor?.argb === "FFFFC000";

const unconfirmedRow = lib.getRow(3); // library[1] is the unconfirmed entry
check('unconfirmed row is marked "NO"', unconfirmedRow.getCell(7).value === "NO", `got ${unconfirmedRow.getCell(7).value}`);
let orangeCells = 0;
unconfirmedRow.eachCell((cell) => {
  if (isOrange(cell)) orangeCells++;
});
check("orange fill (FFFFC000) present on all cells of unconfirmed library row", orangeCells === 7, `orange cells=${orangeCells}`);

const confirmedRow = lib.getRow(2);
let confirmedOrange = 0;
confirmedRow.eachCell((cell) => {
  if (isOrange(cell)) confirmedOrange++;
});
check("confirmed library row has no orange fill", confirmedOrange === 0, `orange cells=${confirmedOrange}`);
check("Cost_Library header frozen+bold", lib.views?.[0]?.state === "frozen" && lib.getRow(1).getCell(1).font?.bold === true);

// ---- verdict ------------------------------------------------------------
console.log(failures === 0 ? "\nRESULT: ALL TESTS PASSED" : `\nRESULT: ${failures} FAILURE(S)`);
process.exitCode = failures === 0 ? 0 : 1;
