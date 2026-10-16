import assert from "node:assert/strict";
import test from "node:test";
import "../assets/ecom-customers.js";

const { analyze, details } = globalThis.EcomCustomerAnalysis;
const names = ["Synthetic Alpha", "Synthetic Beta", "Synthetic Gamma"];
function snapshot(history, asOf = "2026-10-13", overrides = {}) {
  return { schema: 3, generatedAt: "2099-12-31T23:59:00Z", source: { asOf: `${asOf} 19:58` },
    customers: { kind: "name", list: names, historyVersion: 1, asOf,
      statuses: ["Delivered", "Cancelled", "Pending"], history, ...overrides } };
}
const record = (customer, parent, placed, { outlet = 0, suborder = `${parent}-sub`, slot = placed, status = 0, gross = 100, net = status === 1 ? 0 : gross } = {}) =>
  [outlet, customer, parent, suborder, placed, slot, status, gross, net];

test("exactly 30 days qualifies using source data date, independent of build date", () => {
  const d = snapshot([record(0, "A", "2026-09-13"), record(1, "B", "2026-09-14"), record(2, "C", "2026-09-12")]);
  const a = analyze(d, [true], "2026-10");
  assert.equal(a.asOf, "2026-10-13");
  assert.deepEqual(a.rows.map(({ name, status, daysInactive }) => [name, status, daysInactive]), [
    [names[0], "churned", 30], [names[1], "active", 29], [names[2], "churned", 31],
  ]);
  assert.equal(a.churned.customers, 2);
  assert.equal(a.churned.orders, 2);
  assert.equal(a.churned.net, 200);
  assert.equal(a.churned.share, 2 / 3);
  assert.ok(a.rows.every((r) => r.periodOrders === 0), "inactive names remain in the selected month view");
});

test("historical cutoff excludes later placements, including backdated delivery slots", () => {
  const d = snapshot([
    record(0, "old", "2026-08-01"),
    record(0, "later", "2026-10-05", { slot: "2026-09-20", net: 900 }),
    record(1, "future-only", "2026-10-01"),
  ]);
  const a = analyze(d, [true], "2026-09");
  assert.equal(a.asOf, "2026-09-30");
  assert.equal(a.rows.length, 1);
  assert.equal(a.rows[0].status, "churned");
  assert.equal(a.rows[0].lastOrder, "2026-08-01");
  assert.equal(a.rows[0].periodOrders, 0);
  assert.equal(a.totals.net, 100);
  assert.deepEqual(details(d, [true], "2026-09", 0).orders.map((o) => o.order), ["old"]);
  assert.equal(details(d, [true], "2026-09", 1), null);
});

test("parent orders count once across outlets and suborders; amounts follow scope", () => {
  const d = snapshot([
    record(0, "shared", "2026-09-01", { suborder: "s1", outlet: 0, net: 80 }),
    record(0, "shared", "2026-09-10", { suborder: "s2", outlet: 1, net: 120 }),
    record(0, "second", "2026-10-02", { outlet: 1, net: 200 }),
  ]);
  const all = analyze(d, [true, true], "2026-10");
  assert.equal(all.rows[0].orders, 2);
  assert.equal(all.rows[0].suborders, 3);
  assert.equal(all.rows[0].net, 400);
  assert.equal(all.rows[0].status, "active");
  const scoped = analyze(d, [true, false], "2026-10");
  assert.equal(scoped.rows[0].orders, 1);
  assert.equal(scoped.rows[0].net, 80);
  assert.equal(scoped.rows[0].status, "churned");
  const history = details(d, [true, true], "2026-10", 0);
  assert.equal(history.orders.length, 2);
  assert.equal(history.orders[1].order, "shared");
  assert.equal(history.orders[1].placed, "2026-09-01", "parent date is earliest recorded suborder placement");
  assert.equal(history.orders[1].net, 200);
  assert.equal(history.orders[1].suborders, 2);
  assert.deepEqual(history.orders[1].outlets, [0, 1]);
});

test("the earliest placement of a parent drives inactivity, not a later suborder", () => {
  const d = snapshot([record(0, "one-parent", "2026-09-01", { suborder: "a" }), record(0, "one-parent", "2026-09-10", { suborder: "b" })], "2026-10-01");
  assert.equal(analyze(d, [true], "2026-10").rows[0].daysInactive, 30);
});

test("cancelled orders count as placed activity and contribute zero net sales", () => {
  const d = snapshot([record(0, "delivered", "2026-08-01", { gross: 250 }), record(0, "cancelled", "2026-10-10", { status: 1, gross: 500 })]);
  const a = analyze(d, [true], "2026-10");
  assert.equal(a.rows[0].status, "active");
  assert.equal(a.rows[0].orders, 2);
  assert.equal(a.rows[0].net, 250);
  assert.equal(a.rows[0].periodOrders, 1);
  assert.equal(a.rows[0].periodNet, 0);
  const order = details(d, [true], "2026-10", 0).orders[0];
  assert.equal(order.gross, 500);
  assert.equal(order.net, 0);
  assert.deepEqual(order.statuses, ["Cancelled"]);
});

test("monthly ranking uses delivery month while churn uses placement date", () => {
  const d = snapshot([record(0, "prior-placement", "2026-09-12", { slot: "2026-10-01" }), record(1, "future-slot", "2026-10-12", { slot: "2026-11-01", status: 2 })]);
  const a = analyze(d, [true], "2026-10");
  assert.equal(a.rows[0].status, "churned");
  assert.equal(a.rows[0].periodOrders, 1);
  assert.equal(a.rows[0].periodSuborders, 1);
  assert.equal(a.rows[1].status, "active");
  assert.equal(a.rows[1].periodOrders, 0);
  assert.equal(details(d, [true], "2026-10", 1).orders[0].slotFrom, "2026-11-01");
});

test("unknown dates are excluded from impact and cannot imply churn", () => {
  const d = snapshot([record(0, "dated", "2026-08-01"), record(0, "undated", ""), record(1, "invalid", "2026-02-30")]);
  const a = analyze(d, [true], "2026-10");
  assert.equal(a.unknownDates, 2);
  assert.equal(a.unknownCustomers, 2);
  assert.equal(a.churned.customers, 0);
  assert.equal(a.totals.net, 100);
  assert.equal(a.rows[0].status, "unknown");
  assert.equal(a.rows[1].lastOrder, "");
  assert.equal(details(d, [true], "2026-10", 1).orders.length, 0);
  const historical = analyze(d, [true], "2026-09");
  assert.equal(historical.rows.length, 1, "undated-only identities cannot enter an earlier state");
});

test("missing and conflicting identities report distinct-parent coverage without sales attribution", () => {
  const d = snapshot([record(-1, "missing", "2026-09-01"), record(-1, "missing", "2026-09-01", { outlet: 1 }), record(-2, "conflict", "2026-09-02"), record(0, "known", "2026-09-02")]);
  const a = analyze(d, [true, true], "2026-10");
  assert.equal(a.missing, 1); assert.equal(a.conflicts, 1);
  assert.equal(a.rows.length, 1); assert.equal(a.totals.net, 100);
});

test("legacy or invalid reference dates require refresh instead of invented churn", () => {
  assert.equal(analyze({ schema: 2 }, [true], "2026-10"), null);
  assert.equal(analyze({ schema: 3, customers: { kind: "name", list: names, r: [] } }, [true], "2026-10"), null);
  assert.equal(analyze(snapshot([], "not-a-date"), [true], "2026-10"), null);
  assert.equal(analyze(snapshot([]), [true], "2026-99"), null);
  assert.equal(details(snapshot([]), [true], "2026-10", 0), null);
});

test("input remains unchanged, empty scope stays empty and duplicate rows do not inflate totals", () => {
  const row = record(0, "A", "2026-08-01"), d = snapshot([row, [...row]]), before = structuredClone(d);
  const a = analyze(d, [true], "2026-10");
  assert.equal(a.rows[0].suborders, 1);
  assert.equal(a.rows[0].net, 100);
  assert.equal(details(d, [true], "2026-10", 0).orders[0].items.length, 1);
  assert.deepEqual(analyze(d, [false], "2026-10").totals, { customers: 0, orders: 0, net: 0 });
  assert.deepEqual(d, before);
});

test("fractional currency remains precise in contribution and order detail totals", () => {
  const d = snapshot([record(0, "A", "2026-08-01", { suborder: "a", gross: 0.1 }), record(0, "A", "2026-08-01", { suborder: "b", gross: 0.2 })]);
  assert.equal(analyze(d, [true], "2026-10").rows[0].net, 0.3);
  assert.equal(analyze(d, [true], "2026-10").churned.net, 0.3);
  assert.equal(details(d, [true], "2026-10", 0).orders[0].gross, 0.3);
});

test("drawer can reuse current analysis but rejects results from another scope or month", () => {
  const d = snapshot([record(0, "old", "2026-08-01"), record(0, "new", "2026-10-01", { outlet: 1 })]);
  const a = analyze(d, [true, true], "2026-10");
  assert.deepEqual(details(d, [true, true], "2026-10", 0, a), details(d, [true, true], "2026-10", 0));
  assert.deepEqual(details(d, [true, false], "2026-10", 0, a).orders.map((o) => o.order), ["old"]);
  assert.deepEqual(details(d, [true, true], "2026-09", 0, a).orders.map((o) => o.order), ["old"]);
});
