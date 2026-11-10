// Money is added in whole cents so sums never drift (0.1 + 0.2 is not 0.3 in floating point).
// Amounts arrive from the API as strings with two decimals.

export const cents = (value: string | number): number => Math.round(Number(value) * 100);

export const fromCents = (value: number): string => (value / 100).toFixed(2);

export const sumCents = (values: Array<string | number>): number => values.reduce<number>((n, v) => n + cents(v), 0);

/** A running total over `items`, counting only the ones `counts` accepts. One total per item. */
export function runningTotals<T>(items: T[], counts: (item: T) => boolean, amount: (item: T) => string): number[] {
  let running = 0;
  return items.map((item) => {
    if (counts(item)) running += cents(amount(item));
    return running;
  });
}
