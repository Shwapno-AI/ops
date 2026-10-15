import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

// Exercise the shipping aggregation helper without evaluating the application
// bootstrap, access controls, or any real dashboard/customer data.
const appSource = readFileSync(new URL("../assets/app.js", import.meta.url), "utf8");
const startMarker = "  function ecCustomerRanks(d, on, mi) {";
const endMarker = "  function ecCustomerTable(C) {";
const start = appSource.indexOf(startMarker);
const end = appSource.indexOf(endMarker, start);
assert.ok(start >= 0 && end > start, "Customer ranking helper boundaries must exist");
const ecCustomerRanks = new Function(
  appSource.slice(start, end) + "\nreturn ecCustomerRanks;",
)();

function snapshot(rows, names = ["Synthetic Alpha", "Synthetic Beta", "Synthetic Gamma"]) {
  return { schema: 3, customers: { kind: "name", list: names, r: rows } };
}

test("older snapshots without name aggregates are unavailable rather than empty", () => {
  assert.equal(ecCustomerRanks({ schema: 2 }, [true], 0), null);
  assert.equal(ecCustomerRanks({ schema: 3, customers: { kind: "id" } }, [true], 0), null);
});

test("parent orders count once across sub-orders and outlets while amounts accumulate", () => {
  const data = snapshot([
    [0, 0, 0, "parent-a", 3, 450],
    [1, 0, 0, "parent-a", 1, 50],
    [0, 0, 1, "parent-b", 1, 200],
    [1, 0, 1, "parent-c", 2, 400],
    // A cancelled parent still counts as an order and contributes zero net sales.
    [0, 0, 1, "parent-cancelled", 1, 0],
    [0, 0, 2, "parent-d", 1, 100],
    [2, 0, 2, "outside-scope", 99, 9900],
    [0, 1, 0, "different-month", 99, 9900],
  ]);
  const before = structuredClone(data);
  assert.deepEqual(ecCustomerRanks(data, [true, true, false], 0), {
    rows: [
      { name: "Synthetic Beta", suborders: 4, net: 600, orders: 3, rank: 1 },
      { name: "Synthetic Alpha", suborders: 4, net: 500, orders: 1, rank: 2 },
      { name: "Synthetic Gamma", suborders: 1, net: 100, orders: 1, rank: 2 },
    ],
    missing: 0,
    conflicts: 0,
  });
  assert.deepEqual(data, before, "Aggregation must leave the snapshot unchanged");
});

test("outlet filters recalculate orders and sales from only included outlets", () => {
  const data = snapshot([
    [0, 0, 0, "shared-parent", 1, 100],
    [1, 0, 0, "shared-parent", 2, 250],
    [1, 0, 0, "second-parent", 1, 75],
    [0, 0, 1, "other-parent", 1, 120],
  ]);
  const all = ecCustomerRanks(data, [true, true], 0);
  assert.equal(all.rows[0].name, "Synthetic Alpha");
  assert.equal(all.rows[0].orders, 2);
  assert.equal(all.rows[0].net, 425);
  assert.deepEqual(ecCustomerRanks(data, [true, false], 0).rows, [
    { name: "Synthetic Alpha", suborders: 1, net: 100, orders: 1, rank: 1 },
    { name: "Synthetic Beta", suborders: 1, net: 120, orders: 1, rank: 1 },
  ]);
  assert.deepEqual(ecCustomerRanks(data, [false, true], 0).rows, [
    { name: "Synthetic Alpha", suborders: 3, net: 325, orders: 2, rank: 1 },
  ]);
});

test("month filtering neither leaks orders nor carries deduplication between months", () => {
  const data = snapshot([
    [0, 0, 0, "same-parent", 1, 100],
    [0, 1, 0, "same-parent", 1, 200],
    [1, 1, 0, "same-parent", 1, 25],
    [0, 1, 1, "next-parent", 1, 300],
  ]);
  assert.deepEqual(ecCustomerRanks(data, [true, true], 1).rows, [
    { name: "Synthetic Alpha", suborders: 2, net: 225, orders: 1, rank: 1 },
    { name: "Synthetic Beta", suborders: 1, net: 300, orders: 1, rank: 1 },
  ]);
  assert.deepEqual(ecCustomerRanks(data, [true, true], 0).rows, [
    { name: "Synthetic Alpha", suborders: 1, net: 100, orders: 1, rank: 1 },
  ]);
});

test("ties use a deterministic name order and competition ranks", () => {
  const records = [
    [0, 0, 1, "beta-1", 1, 1000],
    [0, 0, 1, "beta-2", 1, 1000],
    [0, 0, 0, "alpha-1", 1, 1],
    [0, 0, 0, "alpha-2", 1, 1],
    [0, 0, 2, "gamma-1", 1, 10000],
  ];
  const result = ecCustomerRanks(snapshot(records), [true], 0);
  assert.deepEqual(result.rows.map(({ name, rank }) => ({ name, rank })), [
    { name: "Synthetic Alpha", rank: 1 },
    { name: "Synthetic Beta", rank: 1 },
    { name: "Synthetic Gamma", rank: 3 },
  ]);
  assert.deepEqual(ecCustomerRanks(snapshot([...records].reverse()), [true], 0), result);
});

test("missing and conflicting names are excluded and coverage counts distinct parents in scope", () => {
  const data = snapshot([
    [0, 0, 0, "known-parent", 1, 100],
    [0, 0, -1, "missing-parent", 1, 100],
    [1, 0, -1, "missing-parent", 2, 200],
    [0, 0, 1, "blank-name-parent", 1, 300],
    [0, 0, -2, "conflicting-parent", 1, 400],
    [1, 0, -2, "conflicting-parent", 1, 500],
    [2, 0, -1, "excluded-outlet", 1, 600],
    [0, 1, -2, "excluded-month", 1, 700],
  ], ["Synthetic Alpha", ""]);
  assert.deepEqual(ecCustomerRanks(data, [true, true, false], 0), {
    rows: [{ name: "Synthetic Alpha", suborders: 1, net: 100, orders: 1, rank: 1 }],
    missing: 2,
    conflicts: 1,
  });
});

test("a valid aggregate with no matching month or outlets is an empty ranking", () => {
  const data = snapshot([[0, 0, 0, "parent-a", 1, 100]]);
  assert.deepEqual(ecCustomerRanks(data, [false], 0), { rows: [], missing: 0, conflicts: 0 });
  assert.deepEqual(ecCustomerRanks(data, [true], 1), { rows: [], missing: 0, conflicts: 0 });
  assert.deepEqual(ecCustomerRanks(snapshot([]), [true], 0), { rows: [], missing: 0, conflicts: 0 });
});
