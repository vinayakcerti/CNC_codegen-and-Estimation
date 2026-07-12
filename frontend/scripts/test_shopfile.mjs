// Hardened import/export tests for src/shopFile.ts ("one shop file" backup).
//
// Covers: pretty-printed export -> import round-trip, non-JSON / non-object
// rejection, missing-section tolerance ("{}" -> 3 warnings + empty arrays),
// garbage hole library rows dropped with a warning, duplicate profile ids
// (last wins + warning), model coercion, rate/addon defaults, and the
// customMachines / myMachines keep rules.
//
// Run from frontend/:  node scripts/test_shopfile.mjs
//
// No test framework and no new dependencies: the script transpiles
// src/shopFile.ts with the local typescript package (transpileModule — the
// module only has type-only imports, so the emitted JS is dependency-free),
// writes it to scripts/.tmp/, imports it, and cleans up.

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { createRequire } from "node:module";
import { isDeepStrictEqual } from "node:util";

const here = path.dirname(fileURLToPath(import.meta.url));
const srcPath = path.join(here, "..", "src", "shopFile.ts");
const tmpDir = path.join(here, ".tmp");

async function loadShopFileModule() {
  const require = createRequire(import.meta.url);
  const ts = require("typescript");
  const out = ts.transpileModule(fs.readFileSync(srcPath, "utf8"), {
    fileName: "shopFile.ts",
    compilerOptions: {
      module: ts.ModuleKind.ESNext,
      target: ts.ScriptTarget.ES2022,
    },
  });
  fs.mkdirSync(tmpDir, { recursive: true });
  const tmpFile = path.join(tmpDir, `shopFile.${process.pid}.${Date.now()}.mjs`);
  fs.writeFileSync(tmpFile, out.outputText);
  try {
    return await import(pathToFileURL(tmpFile).href);
  } finally {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  }
}

const { exportShopFile, importShopFile } = await loadShopFileModule();

// ---- tiny assert harness ----------------------------------------------------
let failures = 0;
function check(desc, ok, detail = "") {
  if (ok) {
    console.log(`PASS: ${desc}`);
  } else {
    failures++;
    console.log(`FAIL: ${desc}${detail ? ` — ${detail}` : ""}`);
  }
}

// ---- fixtures -----------------------------------------------------------------
const profileA = {
  id: "profile-Haas VF-2",
  name: "Haas VF-2",
  model: "ratecard",
  milling_rate_per_cm2: 0.6,
  milling_rate_grinding_per_cm2: 0.8,
  addon_rates: {
    grinding_per_cm2: 0.2,
    plating_per_cm2: 0.5,
    hardening_per_kg: 60,
    powder_per_cm2: 0.35,
  },
  holeLibrary: [
    {
      id: "seed-24-H7-50",
      diameter_mm: 24,
      tolerance: "H7",
      thickness_mm: 50,
      operation: "Drill+Ream",
      cost_inr: 800,
      effective_from: "2026-07-12",
      source: "Reviewer feedback 2026-07",
      confirmed: true,
    },
    {
      id: "seed-24-H7-25",
      diameter_mm: 24,
      tolerance: "H7",
      thickness_mm: 25,
      operation: "Drill+Ream",
      cost_inr: 400,
      effective_from: "2026-07-12",
      source: "estimated (thickness-scaled)",
      confirmed: false,
    },
  ],
  auditLog: [
    {
      at: "2026-07-12T10:00:00.000Z",
      user: "local",
      action: "rate_change",
      before: "0.55",
      after: "0.6",
    },
  ],
};

const profileB = {
  id: "profile-DMG Mori",
  name: "DMG Mori",
  model: "time",
  milling_rate_per_cm2: 0.75,
  milling_rate_grinding_per_cm2: 0.95,
  addon_rates: {
    grinding_per_cm2: 0.25,
    plating_per_cm2: 0.55,
    hardening_per_kg: 65,
    powder_per_cm2: 0.4,
  },
  holeLibrary: [],
  auditLog: [],
};

const machines = [
  {
    name: "Shop VMC 1100",
    max_spindle_rpm: 8000,
    axes: 3,
    rapid_feed_rate: 24000,
    tool_change_time_s: 5,
    setup_time_min: 20,
  },
  {
    name: "Old Bridgeport",
    max_spindle_rpm: 4200,
    axes: 3,
    rapid_feed_rate: 6000,
    tool_change_time_s: 30,
    setup_time_min: 35,
  },
];

const myMachines = ["Haas VF-2", "Shop VMC 1100"];

// ---- 1. export -> import round-trip ------------------------------------------
const text = exportShopFile([profileA, profileB], machines, myMachines);
check("export returns a string", typeof text === "string");
check(
  "export is pretty-printed with 2-space indent",
  text.includes('\n  "version": 1'),
);
const parsed = JSON.parse(text);
check("export sets version 1", parsed.version === 1);
check(
  "export stamps a parseable ISO exported_at",
  typeof parsed.exported_at === "string" &&
    !Number.isNaN(Date.parse(parsed.exported_at)),
  String(parsed.exported_at),
);

const rt = importShopFile(text);
check("round-trip import is ok", rt.ok === true, rt.ok ? "" : rt.error);
check(
  "round-trip import has no warnings",
  rt.ok && rt.warnings.length === 0,
  rt.ok ? rt.warnings.join(" | ") : "",
);
check(
  "round-trip preserves profiles deep-equal",
  rt.ok && isDeepStrictEqual(rt.data.profiles, [profileA, profileB]),
);
check(
  "round-trip preserves customMachines deep-equal",
  rt.ok && isDeepStrictEqual(rt.data.customMachines, machines),
);
check(
  "round-trip preserves myMachines deep-equal",
  rt.ok && isDeepStrictEqual(rt.data.myMachines, myMachines),
);
check("round-trip data.version is 1", rt.ok && rt.data.version === 1);

// ---- 2. non-JSON and non-object input rejected --------------------------------
const notJson = importShopFile("not json");
check(
  'import("not json") -> ok:false with a human error',
  notJson.ok === false &&
    typeof notJson.error === "string" &&
    notJson.error.length > 0,
  notJson.ok ? "unexpectedly ok" : notJson.error,
);
const arrRoot = importShopFile("[1,2,3]");
check("import of a JSON array root -> ok:false", arrRoot.ok === false);
const strRoot = importShopFile('"hello"');
check("import of a JSON string root -> ok:false", strRoot.ok === false);
const nullRoot = importShopFile("null");
check("import of JSON null -> ok:false", nullRoot.ok === false);

// ---- 3. "{}" tolerated: 3 warnings + empty arrays ------------------------------
const empty = importShopFile("{}");
check('import("{}") -> ok:true', empty.ok === true);
check(
  'import("{}") -> exactly 3 warnings (one per missing section)',
  empty.ok && empty.warnings.length === 3,
  empty.ok ? empty.warnings.join(" | ") : "",
);
check(
  'import("{}") -> empty profiles/customMachines/myMachines',
  empty.ok &&
    isDeepStrictEqual(empty.data.profiles, []) &&
    isDeepStrictEqual(empty.data.customMachines, []) &&
    isDeepStrictEqual(empty.data.myMachines, []),
);

// ---- 4. garbage holeLibrary rows dropped, valid kept, defaults applied ---------
const garbage = importShopFile(
  JSON.stringify({
    version: 1,
    profiles: [
      {
        id: "p1",
        name: "Garbage lib",
        holeLibrary: [
          {
            id: "ok-1",
            diameter_mm: 24,
            tolerance: "H7",
            thickness_mm: 50,
            operation: "Drill+Ream",
            cost_inr: 800,
            effective_from: "2026-07-12",
            source: "shop",
            confirmed: true,
          },
          { diameter_mm: "not-a-number", tolerance: "H7", thickness_mm: 50, cost_inr: 800 },
          null,
          { diameter_mm: 24, thickness_mm: 50, cost_inr: 900 }, // no tolerance
          { diameter_mm: 10, tolerance: "H8", thickness_mm: "25", cost_inr: "160" }, // numeric strings coerce
          42,
        ],
      },
    ],
    customMachines: [],
    myMachines: [],
  }),
);
check("garbage-rows import is ok", garbage.ok === true);
const gp = garbage.ok ? garbage.data.profiles[0] : null;
check(
  "invalid hole rows dropped, valid kept (2 of 6)",
  gp !== null && gp.holeLibrary.length === 2,
  gp ? `kept ${gp.holeLibrary.length}` : "",
);
check(
  "kept rows: exact row survives, numeric strings coerced to numbers",
  gp !== null &&
    gp.holeLibrary[0].id === "ok-1" &&
    gp.holeLibrary[1].diameter_mm === 10 &&
    gp.holeLibrary[1].thickness_mm === 25 &&
    gp.holeLibrary[1].cost_inr === 160,
);
check(
  "a warning reports the 4 dropped hole rows",
  garbage.ok && garbage.warnings.some((w) => /dropped 4 invalid hole library row/.test(w)),
  garbage.ok ? garbage.warnings.join(" | ") : "",
);
check(
  "exactly 1 warning for the garbage-rows file",
  garbage.ok && garbage.warnings.length === 1,
  garbage.ok ? garbage.warnings.join(" | ") : "",
);
check(
  "missing milling rates coerced to defaults 0.6 / 0.8",
  gp !== null &&
    gp.milling_rate_per_cm2 === 0.6 &&
    gp.milling_rate_grinding_per_cm2 === 0.8,
);
check(
  "missing addon rates coerced to defaults 0.2 / 0.5 / 60 / 0.35",
  gp !== null &&
    gp.addon_rates.grinding_per_cm2 === 0.2 &&
    gp.addon_rates.plating_per_cm2 === 0.5 &&
    gp.addon_rates.hardening_per_kg === 60 &&
    gp.addon_rates.powder_per_cm2 === 0.35,
);
check(
  "missing auditLog defaults to []",
  gp !== null && isDeepStrictEqual(gp.auditLog, []),
);
check(
  "missing model coerced to \"time\"",
  gp !== null && gp.model === "time",
);

// ---- 5. duplicate profile ids: last wins + warning ------------------------------
const dup = importShopFile(
  JSON.stringify({
    profiles: [
      { id: "p1", name: "First" },
      { id: "p1", name: "Second" },
    ],
    customMachines: [],
    myMachines: [],
  }),
);
check("duplicate ids: exactly one profile survives", dup.ok && dup.data.profiles.length === 1);
check(
  "duplicate ids: the LAST occurrence wins",
  dup.ok && dup.data.profiles[0]?.name === "Second",
  dup.ok ? `got "${dup.data.profiles[0]?.name}"` : "",
);
check(
  "duplicate ids: warning names the id",
  dup.ok && dup.warnings.some((w) => w.includes('"p1"')),
  dup.ok ? dup.warnings.join(" | ") : "",
);
check(
  "duplicate ids: exactly 1 warning",
  dup.ok && dup.warnings.length === 1,
  dup.ok ? dup.warnings.join(" | ") : "",
);

// ---- 6. model coercion ----------------------------------------------------------
const banana = importShopFile(
  JSON.stringify({
    profiles: [{ id: "p2", name: "Banana shop", model: "banana" }],
    customMachines: [],
    myMachines: [],
  }),
);
check(
  'model "banana" coerced to "time"',
  banana.ok && banana.data.profiles[0]?.model === "time",
);
const ratecard = importShopFile(
  JSON.stringify({
    profiles: [{ id: "p3", name: "Rate shop", model: "ratecard" }],
    customMachines: [],
    myMachines: [],
  }),
);
check(
  'model "ratecard" preserved',
  ratecard.ok && ratecard.data.profiles[0]?.model === "ratecard",
);

// ---- extras: machine + pin-list keep rules, invalid profiles skipped -------------
const mixed = importShopFile(
  JSON.stringify({
    profiles: [{ id: 1, name: "numeric id" }, "junk"],
    customMachines: [
      {
        name: "Good machine",
        max_spindle_rpm: 8000,
        axes: 3,
        rapid_feed_rate: 24000,
        tool_change_time_s: 5,
        setup_time_min: 20,
      },
      { name: "" }, // dropped: empty name
      { max_spindle_rpm: 9000 }, // dropped: no name
      "not an object", // dropped
      { name: "Bare name only" }, // kept: numerics default to 0
    ],
    myMachines: ["Haas VF-2", "", 42, null, "   ", "DMG Mori"],
  }),
);
check("profiles without string id+name are skipped", mixed.ok && mixed.data.profiles.length === 0);
check(
  "each skipped profile produced a warning",
  mixed.ok && mixed.warnings.filter((w) => w.startsWith("profiles[")).length === 2,
  mixed.ok ? mixed.warnings.join(" | ") : "",
);
check(
  "customMachines keeps only entries with a non-empty name (2 of 5)",
  mixed.ok && mixed.data.customMachines.length === 2,
  mixed.ok ? JSON.stringify(mixed.data.customMachines.map((m) => m.name)) : "",
);
check(
  "kept machine without numeric fields defaults them to 0",
  mixed.ok &&
    isDeepStrictEqual(mixed.data.customMachines[1], {
      name: "Bare name only",
      max_spindle_rpm: 0,
      axes: 0,
      rapid_feed_rate: 0,
      tool_change_time_s: 0,
      setup_time_min: 0,
    }),
);
check(
  "myMachines keeps only non-empty strings",
  mixed.ok && isDeepStrictEqual(mixed.data.myMachines, ["Haas VF-2", "DMG Mori"]),
  mixed.ok ? JSON.stringify(mixed.data.myMachines) : "",
);

const oddVersion = importShopFile(
  JSON.stringify({ version: 99, profiles: [], customMachines: [], myMachines: [] }),
);
check(
  "unknown version still imports, with a version warning",
  oddVersion.ok &&
    oddVersion.warnings.length === 1 &&
    /version/.test(oddVersion.warnings[0]),
  oddVersion.ok ? oddVersion.warnings.join(" | ") : "",
);

// ---- verdict --------------------------------------------------------------------
console.log(
  failures === 0 ? "\nRESULT: ALL TESTS PASSED" : `\nRESULT: ${failures} FAILURE(S)`,
);
process.exitCode = failures === 0 ? 0 : 1;
