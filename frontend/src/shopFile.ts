// "One shop file" — export / import the user's whole shop setup as a single
// JSON backup: costing profiles (rate cards + hole cost library + audit log),
// user-defined machines, and the "My machines" pin list.
//
// Pure module: no browser globals and no side effects, so it runs unchanged
// in the browser (Settings UI) and in Node (scripts/test_shopfile.mjs).
//
// Import is HARDENED — importShopFile never throws. Non-JSON / non-object
// input is rejected with a human-readable error; everything else is repaired
// section by section (missing sections default to empty, bad rows are
// dropped, out-of-range values fall back to the ARD defaults) and every
// repair is reported in `warnings` so the UI can show what was fixed up.
import type {
  AuditEntry,
  CostingProfile,
  HoleCostRow,
  ToleranceClass,
} from "./costing";
import type { CustomMachine } from "./MachineSelect";

export interface ShopFile {
  version: 1;
  exported_at: string; // ISO timestamp of the export
  profiles: CostingProfile[];
  customMachines: CustomMachine[];
  myMachines: string[]; // machine names pinned in "My machines"
}

export type ShopFileImportResult =
  | { ok: true; data: ShopFile; warnings: string[] }
  | { ok: false; error: string };

// ---- export -----------------------------------------------------------------

export function exportShopFile(
  profiles: CostingProfile[],
  customMachines: CustomMachine[],
  myMachines: string[],
): string {
  const file: ShopFile = {
    version: 1,
    exported_at: new Date().toISOString(),
    profiles,
    customMachines,
    myMachines,
  };
  return JSON.stringify(file, null, 2);
}

// ---- small coercion helpers ---------------------------------------------------

function isObj(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

// Finite number, or a string that parses to one (hand-edited files often
// quote numbers — same leniency as the CSV importer in costing.ts).
function asNum(v: unknown): number | null {
  if (typeof v === "number") return Number.isFinite(v) ? v : null;
  if (typeof v === "string" && v.trim() !== "") {
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

function numOr(v: unknown, dflt: number): number {
  return asNum(v) ?? dflt;
}

function strOr(v: unknown, dflt: string): string {
  return typeof v === "string" && v !== "" ? v : dflt;
}

// ---- per-section coercers -----------------------------------------------------

// A hole row is only worth keeping if the pricing key is intact: numeric
// diameter/thickness/cost and a tolerance string. Everything else defaults.
function coerceHoleRow(v: unknown, idx: number): HoleCostRow | null {
  if (!isObj(v)) return null;
  const dia = asNum(v.diameter_mm);
  const thick = asNum(v.thickness_mm);
  const cost = asNum(v.cost_inr);
  const tol =
    typeof v.tolerance === "string" && v.tolerance.trim() !== ""
      ? (v.tolerance as ToleranceClass)
      : null;
  if (dia === null || thick === null || cost === null || tol === null)
    return null;
  return {
    id: strOr(v.id, `import-${dia}-${tol}-${thick}-${idx}`),
    diameter_mm: dia,
    tolerance: tol,
    thickness_mm: thick,
    operation: strOr(v.operation, "Drill"),
    cost_inr: cost,
    effective_from: strOr(v.effective_from, new Date().toISOString().slice(0, 10)),
    source: strOr(v.source, "shop file import"),
    confirmed: v.confirmed === true, // anything unclear stays "estimated" (orange)
  };
}

function coerceAuditEntry(v: unknown): AuditEntry | null {
  if (!isObj(v)) return null;
  return {
    at: strOr(v.at, ""),
    user: strOr(v.user, ""),
    action: strOr(v.action, ""),
    before: strOr(v.before, ""),
    after: strOr(v.after, ""),
  };
}

// Minimal profile validation: string id + name are required; every other
// field coerces to the ARD default rate card values when absent or invalid.
function coerceProfile(
  v: unknown,
  idx: number,
  warnings: string[],
): CostingProfile | null {
  if (!isObj(v)) {
    warnings.push(`profiles[${idx}]: not an object — skipped`);
    return null;
  }
  const id = typeof v.id === "string" && v.id !== "" ? v.id : null;
  const name = typeof v.name === "string" && v.name !== "" ? v.name : null;
  if (id === null || name === null) {
    warnings.push(`profiles[${idx}]: id and name must be text — skipped`);
    return null;
  }

  let holeLibrary: HoleCostRow[] = [];
  if (Array.isArray(v.holeLibrary)) {
    let dropped = 0;
    v.holeLibrary.forEach((r, i) => {
      const row = coerceHoleRow(r, i);
      if (row) holeLibrary.push(row);
      else dropped++;
    });
    if (dropped > 0) {
      warnings.push(
        `profile "${name}": dropped ${dropped} invalid hole library row(s) ` +
          "(rows need numeric diameter_mm/thickness_mm/cost_inr and a tolerance)",
      );
    }
  } else if (v.holeLibrary !== undefined) {
    warnings.push(`profile "${name}": holeLibrary is not a list — reset to empty`);
    holeLibrary = [];
  }

  const addons = isObj(v.addon_rates) ? v.addon_rates : {};
  const auditLog: AuditEntry[] = Array.isArray(v.auditLog)
    ? v.auditLog
        .map(coerceAuditEntry)
        .filter((e): e is AuditEntry => e !== null)
    : [];

  return {
    id,
    name,
    model: v.model === "ratecard" ? "ratecard" : "time",
    milling_rate_per_cm2: numOr(v.milling_rate_per_cm2, 0.6),
    milling_rate_grinding_per_cm2: numOr(v.milling_rate_grinding_per_cm2, 0.8),
    addon_rates: {
      grinding_per_cm2: numOr(addons.grinding_per_cm2, 0.2),
      plating_per_cm2: numOr(addons.plating_per_cm2, 0.5),
      hardening_per_kg: numOr(addons.hardening_per_kg, 60),
      powder_per_cm2: numOr(addons.powder_per_cm2, 0.35),
    },
    holeLibrary,
    auditLog,
  };
}

function coerceMachine(v: unknown): CustomMachine | null {
  if (!isObj(v) || typeof v.name !== "string" || v.name.trim() === "")
    return null;
  return {
    name: v.name,
    max_spindle_rpm: numOr(v.max_spindle_rpm, 0),
    axes: numOr(v.axes, 0),
    rapid_feed_rate: numOr(v.rapid_feed_rate, 0),
    tool_change_time_s: numOr(v.tool_change_time_s, 0),
    setup_time_min: numOr(v.setup_time_min, 0),
  };
}

// ---- import -------------------------------------------------------------------

export function importShopFile(text: string): ShopFileImportResult {
  let raw: unknown;
  try {
    raw = JSON.parse(text);
  } catch {
    return {
      ok: false,
      error:
        "This file is not valid JSON — expected a shop file exported from this app.",
    };
  }
  if (!isObj(raw)) {
    const got = Array.isArray(raw) ? "a list" : `a ${typeof raw} value`;
    return {
      ok: false,
      error: `Expected a shop file object at the top level, but the file contains ${got}.`,
    };
  }

  const warnings: string[] = [];
  if (raw.version !== undefined && raw.version !== 1) {
    warnings.push(
      `unknown shop file version ${JSON.stringify(raw.version)} — importing as version 1`,
    );
  }

  // profiles — validate each, then dedupe by id (last occurrence wins).
  let profiles: CostingProfile[] = [];
  if (Array.isArray(raw.profiles)) {
    const byId = new Map<string, CostingProfile>();
    raw.profiles.forEach((entry, idx) => {
      const p = coerceProfile(entry, idx, warnings);
      if (!p) return;
      if (byId.has(p.id)) {
        warnings.push(`duplicate profile id "${p.id}" — kept the last occurrence`);
      }
      byId.set(p.id, p);
    });
    profiles = [...byId.values()];
  } else {
    warnings.push('"profiles" section missing or invalid — no rate cards imported');
  }

  // customMachines — keep entries that at least carry a machine name.
  let customMachines: CustomMachine[] = [];
  if (Array.isArray(raw.customMachines)) {
    customMachines = raw.customMachines
      .map(coerceMachine)
      .filter((m): m is CustomMachine => m !== null);
    const dropped = raw.customMachines.length - customMachines.length;
    if (dropped > 0) {
      warnings.push(
        `customMachines: dropped ${dropped} entr${dropped === 1 ? "y" : "ies"} without a machine name`,
      );
    }
  } else {
    warnings.push(
      '"customMachines" section missing or invalid — no custom machines imported',
    );
  }

  // myMachines — pin list is just non-empty machine names.
  let myMachines: string[] = [];
  if (Array.isArray(raw.myMachines)) {
    myMachines = raw.myMachines.filter(
      (s): s is string => typeof s === "string" && s.trim() !== "",
    );
    const dropped = raw.myMachines.length - myMachines.length;
    if (dropped > 0) {
      warnings.push(
        `myMachines: dropped ${dropped} empty or non-text entr${dropped === 1 ? "y" : "ies"}`,
      );
    }
  } else {
    warnings.push('"myMachines" section missing or invalid — pin list not imported');
  }

  return {
    ok: true,
    data: {
      version: 1,
      exported_at: typeof raw.exported_at === "string" ? raw.exported_at : "",
      profiles,
      customMachines,
      myMachines,
    },
    warnings,
  };
}
