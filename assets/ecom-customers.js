/* Customer history analysis uses source dates, never the browser's current clock. */
(() => {
  "use strict";
  const DAY = 86400000;
  // Churn: a regular customer (average order of at least ৳1,000, and at least one order a week: an average gap
  // of 7 days or less between orders over a journey of a week or more) who has placed nothing for 15 days or more.
  // Anyone else without an order for 15 days is "inactive", not churned.
  const RULE = Object.freeze({ days: 15, aov: 1000, perWeek: 1, minOrders: 2 });
  const analysisContexts = new WeakMap();
  const scopeKey = (on) => on.map(Boolean).join(",");
  function day(value) {
    if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return "";
    const time = Date.parse(value + "T00:00:00Z");
    return Number.isFinite(time) && new Date(time).toISOString().slice(0, 10) === value ? value : "";
  }
  const amount = (value) => typeof value === "number" && Number.isFinite(value) ? value : 0;
  const money = (value) => Math.round((value + Number.EPSILON) * 100) / 100;
  function context(d, month) {
    const c = d.customers;
    if (c?.kind !== "name" || c.historyVersion !== 1 || !Array.isArray(c.history)) return null;
    const availableAsOf = day(c.asOf) || day(d.source?.asOf?.slice(0, 10));
    if (!availableAsOf || !/^\d{4}-(0[1-9]|1[0-2])$/.test(month || "")) return null;
    const end = new Date(Date.UTC(+month.slice(0, 4), +month.slice(5, 7), 0)).toISOString().slice(0, 10);
    return { c, availableAsOf, asOf: end < availableAsOf ? end : availableAsOf, month };
  }
  function baseRow(customer, name) {
    return { customer, name, parents: new Map(), parentNet: new Map(), periodParents: new Set(), net: 0, suborders: 0, periodNet: 0, periodSuborders: 0, undated: false };
  }
  function finish(row, asOf) {
    const dates = [...row.parents.values()].filter(Boolean).sort();
    const firstOrder = dates[0] || "", lastOrder = dates.at(-1) || "";
    const daysInactive = lastOrder ? Math.round((Date.parse(asOf) - Date.parse(lastOrder)) / DAY) : null;
    const journeyDays = lastOrder ? Math.round((Date.parse(lastOrder) - Date.parse(firstOrder)) / DAY) + 1 : null;
    const paid = [...row.parentNet.values()].filter((v) => v > 0).length;
    const aov = paid ? money(row.net / paid) : null;
    // orders a week = 7 / the average gap between orders; needs two orders on different days
    const span = journeyDays ? journeyDays - 1 : 0, perWeek = span > 0 ? (7 * (row.parents.size - 1)) / span : null;
    const regular = row.parents.size >= RULE.minOrders && span >= 7 && aov !== null && aov >= RULE.aov && perWeek >= RULE.perWeek;
    const status = daysInactive !== null && daysInactive < RULE.days ? "active" : row.undated || daysInactive === null ? "unknown" : regular ? "churned" : "inactive";
    return { customer: row.customer, name: row.name, status, regular, daysInactive, firstOrder, lastOrder, journeyDays, aov, perWeek,
      orders: row.parents.size, net: money(row.net), suborders: row.suborders,
      periodOrders: row.periodParents.size, periodNet: money(row.periodNet), periodSuborders: row.periodSuborders };
  }
  function analyze(d, on, month) {
    const ctx = context(d, month);
    if (!ctx) return null;
    const { c, asOf, availableAsOf } = ctx, groups = new Map(), missing = new Set(), conflicts = new Set(), seen = new Set();
    let coverageStart = "", unknownDates = 0;
    for (const record of c.history) {
      const [outlet, customer, parent, suborder, placedValue, slotValue, , , net] = record;
      if (!on[outlet]) continue;
      const placed = day(placedValue), slot = day(slotValue), name = c.list[customer];
      if (!placed) {
        unknownDates++;
        // An undated transaction cannot be assigned to an earlier historical state.
        if (asOf === availableAsOf && customer >= 0 && name) {
          if (!groups.has(customer)) groups.set(customer, baseRow(customer, name));
          groups.get(customer).undated = true;
        }
        continue;
      }
      if (placed > asOf || !parent) continue;
      const key = JSON.stringify([parent, suborder, outlet]);
      if (seen.has(key)) continue;
      seen.add(key);
      if (!coverageStart || placed < coverageStart) coverageStart = placed;
      if (customer < 0 || !name) { (customer === -2 ? conflicts : missing).add(parent); continue; }
      if (!groups.has(customer)) groups.set(customer, baseRow(customer, name));
      const row = groups.get(customer), prior = row.parents.get(parent);
      row.parents.set(parent, !prior || placed < prior ? placed : prior);
      row.suborders++; row.net += amount(net); row.parentNet.set(parent, (row.parentNet.get(parent) || 0) + amount(net));
      if (slot.slice(0, 7) === month) { row.periodParents.add(parent); row.periodNet += amount(net); row.periodSuborders++; }
    }
    const rows = [...groups.values()].map((row) => finish(row, asOf))
      .sort((a, b) => b.orders - a.orders || a.name.localeCompare(b.name));
    const totals = rows.reduce((t, row) => ({ customers: t.customers + 1, orders: t.orders + row.orders, net: t.net + row.net }), { customers: 0, orders: 0, net: 0 });
    const churned = rows.filter((row) => row.status === "churned").reduce((t, row) => ({ customers: t.customers + 1, orders: t.orders + row.orders, net: t.net + row.net }), { customers: 0, orders: 0, net: 0 });
    totals.net = money(totals.net); churned.net = money(churned.net);
    churned.share = totals.net > 0 ? churned.net / totals.net : null;
    const result = { asOf, availableAsOf, coverageStart, rows, churned, totals,
      unknownCustomers: rows.filter((row) => row.status === "unknown").length,
      missing: missing.size, conflicts: conflicts.size, unknownDates };
    analysisContexts.set(result, { d, month, scope: scopeKey(on) });
    return result;
  }
  function details(d, on, month, customer, currentAnalysis = null) {
    const prior = currentAnalysis && analysisContexts.get(currentAnalysis);
    const analysis = prior?.d === d && prior.month === month && prior.scope === scopeKey(on)
      ? currentAnalysis : analyze(d, on, month);
    const ctx = context(d, month);
    if (!analysis || !ctx) return null;
    const summary = analysis.rows.find((row) => row.customer === customer);
    if (!summary) return null;
    const groups = new Map(), seen = new Set();
    for (const [outlet, c, parent, suborder, placedValue, slotValue, statusIndex, gross, net] of ctx.c.history) {
      if (c !== customer || !on[outlet] || !parent) continue;
      const placed = day(placedValue), slot = day(slotValue);
      if (!placed || placed > ctx.asOf) continue;
      const key = JSON.stringify([parent, suborder, outlet]);
      if (seen.has(key)) continue;
      seen.add(key);
      if (!groups.has(parent)) groups.set(parent, { order: parent, placed, slotFrom: "", slotTo: "", statuses: new Set(), gross: 0, net: 0, suborders: 0, outlets: new Set(), items: [], hasUndated: false });
      const order = groups.get(parent), status = ctx.c.statuses?.[statusIndex] || "Not recorded";
      if (placed < order.placed) order.placed = placed;
      if (slot && (!order.slotFrom || slot < order.slotFrom)) order.slotFrom = slot;
      if (slot && (!order.slotTo || slot > order.slotTo)) order.slotTo = slot;
      if (!slot) order.hasUndated = true;
      order.statuses.add(status); order.outlets.add(outlet);
      order.gross += amount(gross); order.net += amount(net); order.suborders++;
      order.items.push({ suborder, placed, slot, status, gross: amount(gross), net: amount(net), outlet });
    }
    const orders = [...groups.values()].map((order) => ({ ...order, gross: money(order.gross), net: money(order.net),
      statuses: [...order.statuses].sort(), outlets: [...order.outlets].sort((a, b) => a - b),
      items: order.items.sort((a, b) => a.placed.localeCompare(b.placed) || String(a.suborder).localeCompare(String(b.suborder))) }))
      .sort((a, b) => b.placed.localeCompare(a.placed) || String(a.order).localeCompare(String(b.order)));
    return { asOf: analysis.asOf, availableAsOf: analysis.availableAsOf, coverageStart: analysis.coverageStart, customer: summary, orders };
  }
  globalThis.EcomCustomerAnalysis = Object.freeze({ analyze, details, RULE });
})();
