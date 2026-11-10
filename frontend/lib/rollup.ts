import type { CategoryTotal } from "./api.ts";
import { cents, fromCents as money } from "./money.ts";

export type Grouped = CategoryTotal & { children: CategoryTotal[] };

/**
 * Sub-categories are added into their parent: "Groceries" and "Dining out" count under
 * "Food and dining". A parent with no spending of its own still appears, named from its children.
 * Sums are in whole cents so nothing drifts.
 */
export function rollUp(items: CategoryTotal[]): Grouped[] {
  const groups = new Map<number | null, Grouped>();
  const own = new Map<number, CategoryTotal>();
  for (const c of items) if (c.category_id !== null) own.set(c.category_id, c);

  for (const c of items) {
    const key = c.parent_id ?? c.category_id;
    let group = groups.get(key);
    if (!group) {
      const base: CategoryTotal =
        c.parent_id !== null
          ? own.get(c.parent_id) ?? { ...c, category_id: c.parent_id, name: c.parent_name ?? c.name, income: "0", expense: "0", transactions: 0, parent_id: null, parent_name: null }
          : c;
      group = { ...base, income: "0", expense: "0", transactions: 0, children: [] };
      groups.set(key, group);
    }
    group.income = money(cents(group.income) + cents(c.income));
    group.expense = money(cents(group.expense) + cents(c.expense));
    group.transactions += c.transactions;
    if (c.parent_id !== null) group.children.push(c);
  }
  return [...groups.values()];
}
