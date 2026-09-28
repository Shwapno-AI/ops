#!/usr/bin/env node
// Receiving drill-down snapshot: build data/rcv-drill/.
//
// The Receiving drill-down (business division > category > article > outlet) otherwise asks the public
// Power BI report live, which takes seconds per click. This script asks the same questions for the
// default view (last 28 days, all movements) ahead of time, so those clicks are instant. The server runs
// it every 10 minutes (deploy/entrypoint.sh). Receiving lines for one article at one outlet stay live.
//
//   data/rcv-drill/index.json      business divisions, their categories, and the category files that exist
//   data/rcv-drill/articles.json   every article (company-wide) for the article drawers
//   data/rcv-drill/<d>-<c>.json    one category: its articles and its article x outlet rows (over-receiving)
//
// Everything is asked one category at a time (whole business divisions are too heavy for Power BI).
// A part Power BI will not answer is left out and logged; the page reads that part live instead.
// Uses the browser's client (assets/vendor/rcv-powerbi.js); Node 18+ (global fetch).
// Environment: RCV_DRILL_DIR (default data/rcv-drill), RCV_OUT (rcv.json, for the outlet list),
//              RCV_DRILL_WORKERS (parallel Power BI queries, default 3).
import { mkdir, readdir, readFile, rename, unlink, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { PowerBIDataClient } from "../../assets/vendor/rcv-powerbi.js";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const DIR = process.env.RCV_DRILL_DIR || join(ROOT, "data", "rcv-drill");
const RCV = process.env.RCV_OUT || join(ROOT, "data", "rcv.json");
const WORKERS = Number(process.env.RCV_DRILL_WORKERS) || 3;
const DEFAULT_QUERY = { masterCategory: "all", days: 28 }; // must match rcQuery(RC_DEF) in assets/app.js
const FIELDS = ["Receiving", "Sales", "Inventory", "OverValue", "OverIncidents", "UnderIncidents"];
const TEXT = new Set(["ArticleNo", "ArticleName", "Category", "OutletCode", "OutletName"]);
const ART_FIELDS = ["ArticleNo", "ArticleName", "Receiving", "Sales", "OverValue", "OverIncidents", "UnderIncidents"];
const OUTLET_FIELDS = ["ArticleNo", "OutletCode", "OutletName", "OpeningStock", "Receiving", "TotalSales", "TotalInventory", "ClosingStockReceiving", "CurrentStockSystem", "CurrentStockDay", "StdStockDays", "OverReceiving", "OverValue", "OverScore"];
const log = (m) => console.log(m);
const num = (v) => (v == null || v === "" || !isFinite(Number(v)) ? null : Number(v));
const round = (v) => (num(v) == null ? null : Math.round(num(v) * 100) / 100);
// Keep only the fields the page reads, rounded, to keep the files small.
const slim = (a, keys) => Object.fromEntries(keys.filter((k) => a[k] != null && a[k] !== "").map((k) => [k, TEXT.has(k) ? a[k] : round(a[k])]));

async function pool(items, n, fn) {
  const out = new Array(items.length); let i = 0;
  const worker = async () => { while (i < items.length) { const k = i++; out[k] = await fn(items[k], k); } };
  await Promise.all(Array.from({ length: Math.min(n, items.length) }, worker));
  return out;
}
function addUp(rows, key) {
  const by = new Map();
  rows.forEach((a) => { const k = a[key], t = by.get(k); if (!t) by.set(k, { ...a }); else FIELDS.forEach((f) => { if (a[f] != null) t[f] = (num(t[f]) || 0) + (num(a[f]) || 0); }); });
  return [...by.values()];
}
async function writeJson(file, data) {
  const tmp = file + ".tmp";
  await writeFile(tmp, JSON.stringify(data));
  await rename(tmp, file);
}
// Power BI sometimes refuses a query under load; try twice more, then (for heavy ones) 100 outlets at a time.
let outletCodes = [];
async function ask(q, fn, { batches = false } = {}) {
  let last;
  for (let n = 0; n < 3; n++) {
    try { return await fn(q); } catch (e) { last = e; await new Promise((r) => setTimeout(r, 1500 * (n + 1))); }
  }
  if (!batches || !outletCodes.length) throw last;
  const parts = [];
  for (let i = 0; i < outletCodes.length; i += 100) parts.push(outletCodes.slice(i, i + 100));
  const out = [];
  for (const codes of parts) out.push(...(await fn({ ...q, outletCodes: codes })));
  return out;
}

async function main() {
  const t0 = Date.now();
  try { outletCodes = (JSON.parse(await readFile(RCV, "utf8")).outlets || []).map((o) => o.c).filter(Boolean); } catch { log("rcv.json not read; heavy categories cannot be split by outlet."); }
  await mkdir(DIR, { recursive: true });
  const c = await new PowerBIDataClient().connect();
  const divs = c.scope.masterCategories;
  const index = { schema: 2, generatedAt: null, query: DEFAULT_QUERY, powerBiRefreshedAt: c.sourceTimestamp, divisions: [], categories: {}, files: {} };
  const warn = (name, e) => log(`::warning::${name}: ${e.message || e}; read live instead.`);

  // Level 1 and 2: business division totals and their categories (one division at a time; these are light).
  for (const mc of divs) {
    const q = { ...DEFAULT_QUERY, masterCategory: mc };
    try { index.divisions.push({ mc, ...slim(addUp((await ask(q, async (y) => (await c.load(y, { section: "kpis" })).kpis || [], { batches: true })).map((x) => ({ ...x, key: 1 })), "key")[0] || {}, FIELDS) }); } catch (e) { warn(`${mc} totals`, e); }
    try { index.categories[mc] = addUp(await ask(q, async (y) => (await c.load(y, { section: "snapshotBreakdowns" })).categories || [], { batches: true }), "Category").map((a) => slim(a, ["Category", ...FIELDS])); } catch (e) { warn(`${mc} categories`, e); }
  }
  if (index.divisions.length !== divs.length) index.divisions = null;
  log(`  totals and categories (${Math.round((Date.now() - t0) / 1000)} s)`);

  // Level 3 and 4: for each category, its articles and its article x outlet rows.
  const jobs = divs.flatMap((mc, d) => (index.categories[mc] || []).map((x, k) => ({ mc, d, k, cat: x.Category })).filter((j) => j.cat));
  const all = [];
  let failed = 0;
  await pool(jobs, WORKERS, async ({ mc, d, k, cat }) => {
    const q = { ...DEFAULT_QUERY, masterCategory: mc, category: cat }, file = { schema: 2, mc, cat, generatedAt: null, articles: null, outlets: null };
    try {
      const by = new Map();
      for (const m of ["Gap", "OverIncidents", "UnderIncidents", "OverValue"]) {
        addUp(await ask(q, async (y) => (await c.loadArticleDetails(y, m)).rows || [], { batches: true }), "ArticleNo").forEach((a) => by.set(a.ArticleNo, { ...(by.get(a.ArticleNo) || {}), ...a }));
      }
      file.articles = [...by.values()].map((a) => slim(a, ART_FIELDS));
      all.push(...file.articles.map((a) => [d, k, a]));
    } catch (e) { failed++; warn(`${mc} / ${cat} articles`, e); }
    try {
      // stored as arrays in OUTLET_FIELDS order (half the size of objects)
      file.outletFields = OUTLET_FIELDS;
      file.outlets = (await ask(q, async (y) => (await c.loadManagementTable(y, 1, null, { complete: true })).rows || [], { batches: true })).filter((r) => r.OutletCode)
        .map((a) => { const s = slim(a, OUTLET_FIELDS); return OUTLET_FIELDS.map((f) => s[f] ?? null); });
    } catch (e) { failed++; warn(`${mc} / ${cat} article x outlet`, e); }
    if (file.articles || file.outlets) {
      file.generatedAt = new Date().toISOString();
      await writeJson(join(DIR, `${d}-${k}.json`), file);
      (index.files[mc] ||= {})[cat] = { f: `${d}-${k}`, generatedAt: file.generatedAt, articles: !!file.articles, outlets: !!file.outlets };
    }
  });
  log(`  ${jobs.length} categories (${Math.round((Date.now() - t0) / 1000)} s, ${failed} parts failed)`);
  if (!index.divisions && !Object.keys(index.files).length) throw new Error("Power BI answered nothing");

  // Company-wide article list; "missing" names the categories whose articles did not come back
  // (the page asks Power BI live for anything that needs them).
  index.generatedAt = new Date().toISOString();
  const missing = jobs.filter((j) => !index.files[j.mc]?.[j.cat]?.articles).map((j) => [j.mc, j.cat]);
  await writeJson(join(DIR, "articles.json"), { schema: 2, generatedAt: index.generatedAt, divisions: divs, categories: divs.map((mc) => (index.categories[mc] || []).map((x) => x.Category)), missing, fields: ART_FIELDS, rows: all.map(([d, k, a]) => [d, k, ...ART_FIELDS.map((f) => a[f] ?? null)]) });
  index.articles = index.generatedAt;
  await writeJson(join(DIR, "index.json"), index);
  // Drop category files of categories that no longer exist.
  const keep = new Set(Object.values(index.files).flatMap((m) => Object.values(m).map((x) => `${x.f}.json`)).concat(["index.json", "articles.json"]));
  for (const f of await readdir(DIR)) if (f.endsWith(".json") && !keep.has(f)) await unlink(join(DIR, f)).catch(() => {});
  log(`Wrote ${DIR} in ${Math.round((Date.now() - t0) / 1000)} s.`);
}
main().catch((e) => { console.error(`Receiving drill snapshot failed: ${e.message || e}; the last good files are kept.`); process.exit(1); });
