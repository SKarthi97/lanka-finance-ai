import assert from "node:assert/strict";
import { test } from "node:test";
import { rollUp } from "./rollup.ts";

type Item = Parameters<typeof rollUp>[0][number];

const item = (over: Partial<Item>): Item => ({
  category_id: 1,
  name: "Food and dining",
  kind: "expense",
  income: "0.00",
  expense: "0.00",
  transactions: 0,
  parent_id: null,
  parent_name: null,
  ...over,
});

test("a sub-category is added into its parent", () => {
  const grouped = rollUp([
    item({ category_id: 1, name: "Food and dining", expense: "100.10", transactions: 2 }),
    item({ category_id: 2, name: "Groceries", expense: "200.20", transactions: 3, parent_id: 1, parent_name: "Food and dining" }),
  ]);
  assert.equal(grouped.length, 1);
  assert.equal(grouped[0].category_id, 1);
  assert.equal(grouped[0].expense, "300.30"); // exact, not 300.30000000000004
  assert.equal(grouped[0].transactions, 5);
  assert.deepEqual(grouped[0].children.map((c) => c.name), ["Groceries"]);
});

test("a parent with no spending of its own still appears, named from its children", () => {
  const grouped = rollUp([
    item({ category_id: 2, name: "Groceries", expense: "50.00", parent_id: 1, parent_name: "Food and dining" }),
    item({ category_id: 3, name: "Dining out", expense: "25.50", parent_id: 1, parent_name: "Food and dining" }),
  ]);
  assert.equal(grouped.length, 1);
  assert.equal(grouped[0].name, "Food and dining");
  assert.equal(grouped[0].category_id, 1);
  assert.equal(grouped[0].expense, "75.50");
  assert.equal(grouped[0].children.length, 2);
});

test("unrelated categories stay apart and uncategorised stays on its own", () => {
  const grouped = rollUp([
    item({ category_id: 1, name: "Fuel", expense: "10.00" }),
    item({ category_id: null, name: "Uncategorised", kind: null, expense: "5.00" }),
  ]);
  assert.deepEqual(grouped.map((g) => g.name).sort(), ["Fuel", "Uncategorised"]);
});
