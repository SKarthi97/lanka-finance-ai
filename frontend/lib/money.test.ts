import assert from "node:assert/strict";
import { test } from "node:test";
import { cents, fromCents, runningTotals, sumCents } from "./money.ts";

test("amounts are added in whole cents, so nothing drifts", () => {
  assert.equal(0.1 + 0.2 === 0.3, false); // the problem being avoided
  assert.equal(fromCents(sumCents(["0.10", "0.20"])), "0.30");
  assert.equal(fromCents(sumCents(Array.from({ length: 100 }, () => "0.01"))), "1.00");
});

test("cents rounds to the nearest cent and keeps the sign", () => {
  assert.equal(cents("1234.56"), 123456);
  assert.equal(cents("-0.05"), -5);
  assert.equal(cents("2.675"), 268);
  assert.equal(cents(0), 0);
});

test("a running total counts only the items that count", () => {
  const months = [
    { has: true, net: "100.00" },
    { has: false, net: "999.00" }, // a month with no statements: not added
    { has: true, net: "-30.50" },
  ];
  const totals = runningTotals(months, (m) => m.has, (m) => m.net);
  assert.deepEqual(totals, [10000, 10000, 6950]);
});

test("a running total over nothing is empty", () => {
  assert.deepEqual(runningTotals([], () => true, () => "0"), []);
});
