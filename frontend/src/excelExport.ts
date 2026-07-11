// Self-contained Excel workbook generator (ARD R1) — turns a fully-costed
// quote payload into a downloadable per-part cost-split workbook.
//
// exceljs is dynamically imported inside buildWorkbook so it never lands in
// the main app bundle — it's ~1MB and only needed on the "Export to Excel"
// click path, not on initial page load.
//
// Workbook layout:
//   Summary          - one row per part + TOTAL row + reconciliation line
//   <part>_Ops       \
//   <part>_Holes      } three sheets per part, in payload.parts order
//   <part>_Features  /
//   Cost_Library     - rate-card rows, unconfirmed rows filled orange
//
// This module only builds the workbook from a plain-data payload. It does
// not fetch data, does not touch App state, and does not trigger a
// download — the caller owns turning the returned Blob into a save action.
// It runs in both the browser (Vite bundles exceljs's browser build) and
// Node (the test script re-reads real output), so nothing here may touch
// browser-only or node-only globals.

import type { Row, Workbook } from "exceljs";

export interface WorkbookPayload {
  filename: string;
  currencySymbol: string; // display only, e.g. "₹"
  costingModel: "time" | "ratecard";
  library: {
    category: string;
    sub: string;
    unit: string;
    rate: number;
    effectiveFrom: string;
    source: string;
    confirmed: boolean;
  }[];
  parts: {
    name: string;
    bodyIndex: number;
    material: string;
    quantity: number;
    weightKg: number | null;
    machinedAreaCm2: number;
    holeCount: number;
    addons: string[];
    costInr: number;
    cycleMin: number;
    purchased?: boolean;
    ops: {
      opNum: number;
      setup: string;
      opType: string;
      tool: string;
      feature: string;
      depthMm: number | null;
      cutLenMm: number | null;
      cycleMin: number;
      areaCm2: number;
      costInr: number | null;
      costNote?: string;
    }[];
    holes: {
      id: string;
      diaMm: number;
      tolerance: string;
      thicknessMm: number | null;
      thread: string;
      through: string;
      costInr: number | null;
      fallback: boolean;
      counterDiaMm?: number | null;
      counterDepthMm?: number | null;
    }[];
    features: {
      type: string;
      name: string;
      dia: number | null;
      l: number | null;
      w: number | null;
      depth: number | null;
      confidence: string;
      setup: string;
    }[];
  }[];
  totals: { estimatorTotal: number };
}

type PartPayload = WorkbookPayload["parts"][number];

// ---- Number formats ---------------------------------------------------
const FMT_MONEY = "#,##0.00"; // money, areas, minutes, mm
const FMT_COUNT = "#,##0"; // integer counts

// ---- Styling ------------------------------------------------------------
// ARD: UNCONFIRMED cost-library rows get an orange fill.
const ORANGE_ARGB = "FFFFC000";
const ORANGE_FILL = {
  type: "pattern",
  pattern: "solid",
  fgColor: { argb: ORANGE_ARGB },
} as const;

const FROZEN_HEADER = { state: "frozen", ySplit: 1 } as const;

function boldRow(row: Row): void {
  row.eachCell((cell) => {
    cell.font = { ...cell.font, bold: true };
  });
}

// ---- Sheet-name safety --------------------------------------------------
// Excel hard limits: 31 chars max, none of []:*?/\ , unique per workbook,
// not blank. `suffixLen` reserves room for a caller-appended suffix (e.g.
// "_Features" = 9 chars) so base + suffix still fits in 31 and all three
// sibling sheets of a part truncate the part name identically.
const SHEET_NAME_MAX = 31;
const ILLEGAL_SHEET_CHARS = /[[\]:*?/\\]/g;

function sanitizeSheetNameBase(raw: string, suffixLen: number): string {
  let cleaned = raw.replace(ILLEGAL_SHEET_CHARS, "_").trim();
  if (!cleaned) cleaned = "Sheet";
  const maxBaseLen = Math.max(1, SHEET_NAME_MAX - suffixLen);
  if (cleaned.length > maxBaseLen) cleaned = cleaned.slice(0, maxBaseLen).trimEnd();
  return cleaned;
}

// Dedupe a desired sheet name against names already used in this workbook,
// truncating further when needed to make room for the " (n)" disambiguator.
function dedupeSheetName(desired: string, used: Set<string>): string {
  if (!used.has(desired)) {
    used.add(desired);
    return desired;
  }
  for (let n = 2; n < 1000; n++) {
    const suffix = ` (${n})`;
    const base =
      desired.length + suffix.length > SHEET_NAME_MAX
        ? desired.slice(0, SHEET_NAME_MAX - suffix.length)
        : desired;
    const candidate = `${base}${suffix}`;
    if (!used.has(candidate)) {
      used.add(candidate);
      return candidate;
    }
  }
  // Practically unreachable (needs 1000 collisions) — stay total, don't throw.
  const fallback = `${desired.slice(0, SHEET_NAME_MAX - 6)}_${Date.now() % 100000}`;
  used.add(fallback);
  return fallback;
}

function buildPartSheetNames(
  partName: string,
  used: Set<string>,
): { ops: string; holes: string; features: string } {
  // Reserve room for the longest suffix ("_Features") so all three sibling
  // sheets share one truncation of the part name.
  const base = sanitizeSheetNameBase(partName, "_Features".length);
  return {
    ops: dedupeSheetName(`${base}_Ops`, used),
    holes: dedupeSheetName(`${base}_Holes`, used),
    features: dedupeSheetName(`${base}_Features`, used),
  };
}

// ---- Summary sheet --------------------------------------------------------
function addSummarySheet(wb: Workbook, p: WorkbookPayload, used: Set<string>): void {
  const sheet = wb.addWorksheet(dedupeSheetName("Summary", used));
  sheet.columns = [
    { header: "Part name", key: "name", width: 30 },
    { header: "Body index", key: "bodyIndex", width: 11, style: { numFmt: FMT_COUNT } },
    { header: "Material", key: "material", width: 16 },
    { header: "Qty", key: "qty", width: 8, style: { numFmt: FMT_COUNT } },
    { header: "Weight (kg)", key: "weightKg", width: 12, style: { numFmt: FMT_MONEY } },
    { header: "Machined area (cm²)", key: "areaCm2", width: 19, style: { numFmt: FMT_MONEY } },
    { header: "Hole count", key: "holeCount", width: 11, style: { numFmt: FMT_COUNT } },
    { header: "Add-on processes", key: "addons", width: 28 },
    { header: "Cost (INR)", key: "cost", width: 14, style: { numFmt: FMT_MONEY } },
    { header: "Cycle time (min)", key: "cycleMin", width: 15, style: { numFmt: FMT_MONEY } },
  ];
  boldRow(sheet.getRow(1));
  sheet.views = [FROZEN_HEADER];

  let sumCost = 0;
  let sumCycle = 0;
  for (const part of p.parts) {
    // ARD: purchased parts appear on the Summary with 0 cost and a
    // "purchased — not machined" marker in the Add-ons column.
    const purchased = part.purchased === true;
    const cost = purchased ? 0 : part.costInr;
    sheet.addRow({
      name: part.name,
      bodyIndex: part.bodyIndex,
      material: part.material,
      qty: part.quantity,
      weightKg: part.weightKg ?? "",
      areaCm2: part.machinedAreaCm2,
      holeCount: part.holeCount,
      addons: purchased ? "purchased — not machined" : part.addons.join(", "),
      cost,
      cycleMin: part.cycleMin,
    });
    sumCost += cost;
    sumCycle += part.cycleMin;
  }

  const totalRow = sheet.addRow({ name: "TOTAL", cost: sumCost, cycleMin: sumCycle });
  boldRow(totalRow);

  // Reconciliation: Σ(Summary cost column) vs the estimator's own total.
  const sym = p.currencySymbol || "";
  const delta = sumCost - p.totals.estimatorTotal;
  const status = Math.abs(delta) <= 0.01 ? "OK" : "MISMATCH"; // a paisa of float slop is fine
  sheet.addRow({});
  const reconRow = sheet.addRow({
    name:
      `Reconciliation: Σ part cost = ${sym}${sumCost.toFixed(2)}, ` +
      `estimator total = ${sym}${p.totals.estimatorTotal.toFixed(2)}, ` +
      `delta = ${sym}${delta.toFixed(2)} — ${status}`,
  });
  reconRow.eachCell((cell) => {
    cell.font = { italic: true, bold: status === "MISMATCH" };
  });
  sheet.addRow({ name: `Costing model: ${p.costingModel}` });
}

// ---- Per-part Ops / Holes / Features sheets ------------------------------
function addOpsSheet(wb: Workbook, sheetName: string, part: PartPayload): void {
  const sheet = wb.addWorksheet(sheetName);
  sheet.columns = [
    { header: "Op #", key: "opNum", width: 7, style: { numFmt: FMT_COUNT } },
    { header: "Setup", key: "setup", width: 16 },
    { header: "Op type", key: "opType", width: 16 },
    { header: "Tool", key: "tool", width: 22 },
    { header: "Feature", key: "feature", width: 18 },
    { header: "Depth (mm)", key: "depthMm", width: 11, style: { numFmt: FMT_MONEY } },
    { header: "Cut length (mm)", key: "cutLenMm", width: 15, style: { numFmt: FMT_MONEY } },
    { header: "Cycle (min)", key: "cycleMin", width: 11, style: { numFmt: FMT_MONEY } },
    { header: "Area (cm²)", key: "areaCm2", width: 11, style: { numFmt: FMT_MONEY } },
    { header: "Cost (INR)", key: "costInr", width: 12, style: { numFmt: FMT_MONEY } },
    { header: "Cost note", key: "costNote", width: 24 },
  ];
  boldRow(sheet.getRow(1));
  sheet.views = [FROZEN_HEADER];
  for (const op of part.ops) {
    sheet.addRow({
      opNum: op.opNum,
      setup: op.setup,
      opType: op.opType,
      tool: op.tool,
      feature: op.feature,
      depthMm: op.depthMm ?? "",
      cutLenMm: op.cutLenMm ?? "",
      cycleMin: op.cycleMin,
      areaCm2: op.areaCm2,
      costInr: op.costInr ?? "",
      costNote: op.costNote ?? "",
    });
  }
}

function addHolesSheet(wb: Workbook, sheetName: string, part: PartPayload): void {
  const sheet = wb.addWorksheet(sheetName);
  sheet.columns = [
    { header: "ID", key: "id", width: 9 },
    { header: "Dia (mm)", key: "diaMm", width: 10, style: { numFmt: FMT_MONEY } },
    { header: "Tolerance", key: "tolerance", width: 11 },
    { header: "Thickness (mm)", key: "thicknessMm", width: 14, style: { numFmt: FMT_MONEY } },
    { header: "Thread", key: "thread", width: 11 },
    { header: "Through", key: "through", width: 9 },
    { header: "Counter dia (mm)", key: "counterDiaMm", width: 16, style: { numFmt: FMT_MONEY } },
    { header: "Counter depth (mm)", key: "counterDepthMm", width: 17, style: { numFmt: FMT_MONEY } },
    { header: "Cost (INR)", key: "costInr", width: 12, style: { numFmt: FMT_MONEY } },
    { header: "estimated?", key: "estimated", width: 11 },
  ];
  boldRow(sheet.getRow(1));
  sheet.views = [FROZEN_HEADER];
  for (const hole of part.holes) {
    sheet.addRow({
      id: hole.id,
      diaMm: hole.diaMm,
      tolerance: hole.tolerance,
      thicknessMm: hole.thicknessMm ?? "",
      thread: hole.thread,
      through: hole.through,
      counterDiaMm: hole.counterDiaMm ?? "",
      counterDepthMm: hole.counterDepthMm ?? "",
      costInr: hole.costInr ?? "",
      estimated: hole.fallback ? "YES" : "", // ARD: fallback flag column
    });
  }
}

function addFeaturesSheet(wb: Workbook, sheetName: string, part: PartPayload): void {
  const sheet = wb.addWorksheet(sheetName);
  sheet.columns = [
    { header: "Type", key: "type", width: 14 },
    { header: "Name", key: "name", width: 22 },
    { header: "Dia", key: "dia", width: 10, style: { numFmt: FMT_MONEY } },
    { header: "L", key: "l", width: 10, style: { numFmt: FMT_MONEY } },
    { header: "W", key: "w", width: 10, style: { numFmt: FMT_MONEY } },
    { header: "Depth", key: "depth", width: 10, style: { numFmt: FMT_MONEY } },
    { header: "Confidence", key: "confidence", width: 12 },
    { header: "Setup", key: "setup", width: 16 },
  ];
  boldRow(sheet.getRow(1));
  sheet.views = [FROZEN_HEADER];
  for (const f of part.features) {
    sheet.addRow({
      type: f.type,
      name: f.name,
      dia: f.dia ?? "",
      l: f.l ?? "",
      w: f.w ?? "",
      depth: f.depth ?? "",
      confidence: f.confidence,
      setup: f.setup,
    });
  }
}

// ---- Cost_Library sheet ----------------------------------------------
function addCostLibrarySheet(wb: Workbook, p: WorkbookPayload, used: Set<string>): void {
  const sheet = wb.addWorksheet(dedupeSheetName("Cost_Library", used));
  sheet.columns = [
    { header: "Category", key: "category", width: 18 },
    { header: "Sub-category", key: "sub", width: 22 },
    { header: "Unit", key: "unit", width: 9 },
    { header: "Rate (INR)", key: "rate", width: 12, style: { numFmt: FMT_MONEY } },
    { header: "Effective date", key: "effectiveFrom", width: 14 },
    { header: "Source", key: "source", width: 18 },
    { header: "Confirmed", key: "confirmed", width: 11 },
  ];
  boldRow(sheet.getRow(1));
  sheet.views = [FROZEN_HEADER];
  for (const entry of p.library) {
    const row = sheet.addRow({
      category: entry.category,
      sub: entry.sub,
      unit: entry.unit,
      rate: entry.rate,
      effectiveFrom: entry.effectiveFrom,
      source: entry.source,
      confirmed: entry.confirmed ? "YES" : "NO",
    });
    if (!entry.confirmed) {
      row.eachCell((cell) => {
        cell.fill = ORANGE_FILL;
      });
    }
  }
}

// ---- Public entry point ------------------------------------------------
const XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";

export async function buildWorkbook(p: WorkbookPayload): Promise<Blob> {
  // Dynamic import keeps exceljs (~1MB) out of the main bundle — it is only
  // fetched when a workbook export is actually requested. exceljs ships as
  // CJS, so under Node ESM interop the classes live on `default`; some
  // bundlers instead flatten them onto the namespace — cover both.
  const mod = await import("exceljs");
  const ExcelJS = mod.default ?? mod;

  const wb = new ExcelJS.Workbook();
  wb.creator = "CNC Plan & Process Pro";
  wb.created = new Date();
  wb.title = p.filename;

  const usedSheetNames = new Set<string>();
  addSummarySheet(wb, p, usedSheetNames);
  for (const part of p.parts) {
    const names = buildPartSheetNames(part.name, usedSheetNames);
    addOpsSheet(wb, names.ops, part);
    addHolesSheet(wb, names.holes, part);
    addFeaturesSheet(wb, names.features, part);
  }
  addCostLibrarySheet(wb, p, usedSheetNames);

  // Node returns a real Buffer, the browser build an ArrayBuffer-backed
  // polyfill — both are valid Blob parts, so one code path covers the app
  // and the Node test script.
  const buffer = await wb.xlsx.writeBuffer();
  return new Blob([buffer], { type: XLSX_MIME });
}
