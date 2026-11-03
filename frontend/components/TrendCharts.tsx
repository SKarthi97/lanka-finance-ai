"use client";

import Link from "next/link";
import { useState } from "react";
import { TrendMonth } from "@/lib/api";
import { MONTHS, formatMoney } from "@/lib/format";

// Chart values are for drawing only (never shown as figures without formatMoney, never summed
// into totals); the amounts themselves stay exact decimal strings from the API.
const W = 720;
const H = 200;
const PAD = { top: 12, right: 8, bottom: 24, left: 8 };

const INCOME = "#60a5fa"; // blue
const EXPENSE = "#ff7a59"; // coral: distinguishable from blue without relying on red/green
const BALANCE = "#e2e8f0";

function compact(n: number): string {
  const abs = Math.abs(n);
  if (abs >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (abs >= 1_000) return `${(n / 1_000).toFixed(0)}K`;
  return n.toFixed(0);
}

function monthHref(m: TrendMonth, bank: string): string {
  const params = new URLSearchParams({ year: String(m.year), month: String(m.month) });
  if (bank) params.set("bank_code", bank);
  return `/transactions?${params}`;
}


/** Floating readout for the hovered month; positioned as a share of the chart width. */
function Tooltip({ index, count, title, lines }: { index: number; count: number; title: string; lines: [string, string, string][] }) {
  const left = ((index + 0.5) / count) * 100;
  return (
    <div
      role="presentation"
      style={{ left: `${left}%` }}
      className={`pointer-events-none absolute top-0 z-10 w-max max-w-[14rem] rounded border border-slate-300 bg-chrome px-3 py-2 text-xs shadow-lg ${
        left > 60 ? "-translate-x-full" : left < 40 ? "" : "-translate-x-1/2"
      }`}
    >
      <div className="mb-1 font-medium text-slate-900">{title}</div>
      {lines.map(([label, value, color]) => (
        <div key={label} className="flex items-center justify-between gap-4">
          <span className="flex items-center gap-1 text-slate-600">
            <span className="inline-block h-2 w-2 rounded-sm" style={{ background: color }} />
            {label}
          </span>
          <span className="tabular-nums text-slate-900">{value}</span>
        </div>
      ))}
    </div>
  );
}

export function IncomeExpenseChart({
  months,
  bank,
  onPick,
  selected,
}: {
  months: TrendMonth[];
  bank: string;
  onPick: (year: number, month: number) => void;
  selected: { year: number; month: number };
}) {
  const max = Math.max(1, ...months.flatMap((m) => [Number(m.income), Number(m.expense)]));
  const plotH = H - PAD.top - PAD.bottom;
  const slot = (W - PAD.left - PAD.right) / months.length;
  const barW = Math.min(18, slot / 2.6);
  const [hover, setHover] = useState<number | null>(null);
  const hovered = hover === null ? null : months[hover];

  return (
    <div className="relative">
      {hovered && hover !== null && (
        <Tooltip
          index={hover}
          count={months.length}
          title={`${MONTHS[hovered.month - 1]} ${hovered.year}`}
          lines={[
            ["Income", formatMoney(hovered.income), INCOME],
            ["Expense", formatMoney(hovered.expense), EXPENSE],
            ["Net", formatMoney(hovered.net), "#98a1b0"],
          ]}
        />
      )}
      <table className="sr-only">
        <caption>Income and expense by month</caption>
        <thead>
          <tr><th>Month</th><th>Income</th><th>Expense</th></tr>
        </thead>
        <tbody>
          {months.map((m) => (
            <tr key={`${m.year}-${m.month}`}>
              <td>{MONTHS[m.month - 1]} {m.year}</td>
              <td>{formatMoney(m.income)}</td>
              <td>{formatMoney(m.expense)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <svg aria-hidden="true" viewBox={`0 0 ${W} ${H}`} className="w-full" >
        <line x1={PAD.left} x2={W - PAD.right} y1={H - PAD.bottom} y2={H - PAD.bottom} stroke="#434859" />
        {months.map((m, i) => {
          const x = PAD.left + i * slot + slot / 2;
          const inc = (Number(m.income) / max) * plotH;
          const exp = (Number(m.expense) / max) * plotH;
          const active = m.year === selected.year && m.month === selected.month;
          return (
            <g key={`${m.year}-${m.month}`}>
              {active && (
                <rect x={x - slot / 2 + 2} y={PAD.top - 6} width={slot - 4} height={plotH + 6} fill="#2b2e3a" />
              )}
              <rect x={x - barW - 1} y={H - PAD.bottom - inc} width={barW} height={Math.max(inc, 0)} fill={INCOME} rx="2">
                <title>{`${MONTHS[m.month - 1]} ${m.year} income ${formatMoney(m.income)}`}</title>
              </rect>
              <rect x={x + 1} y={H - PAD.bottom - exp} width={barW} height={Math.max(exp, 0)} fill={EXPENSE} rx="2">
                <title>{`${MONTHS[m.month - 1]} ${m.year} expense ${formatMoney(m.expense)}`}</title>
              </rect>
              {/* Whole slot is a button: pick the month; the label below opens its transactions. */}
              <rect
                x={x - slot / 2}
                y={PAD.top - 6}
                width={slot}
                height={plotH + 6}
                fill="transparent"
                className="cursor-pointer"
                onClick={() => onPick(m.year, m.month)}
                onMouseEnter={() => setHover(i)}
                onMouseLeave={() => setHover(null)}
              >
                <title>{`Show ${MONTHS[m.month - 1]} ${m.year}`}</title>
              </rect>
              <text x={x} y={H - 8} textAnchor="middle" fontSize="11" fill={active ? "#eef1f6" : "#98a1b0"} fontWeight={active ? 600 : 400}>
                {MONTHS[m.month - 1]}
              </text>
            </g>
          );
        })}
      </svg>
      <div className="mt-1 flex flex-wrap items-center gap-4 text-xs text-slate-600">
        <span className="flex items-center gap-1">
          <span className="inline-block h-2 w-3 rounded-sm" style={{ background: INCOME }} /> Income
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block h-2 w-3 rounded-sm" style={{ background: EXPENSE }} /> Expense
        </span>
        <span className="text-slate-400">Peak {compact(max)} · hover for figures, click a month to select it</span>
        <Link
          href={monthHref(
            months.find((m) => m.year === selected.year && m.month === selected.month) ?? months[months.length - 1],
            bank,
          )}
          className="ml-auto underline"
        >
          Transactions for {MONTHS[selected.month - 1]} {selected.year}
        </Link>
      </div>
    </div>
  );
}

export function BalanceChart({ months }: { months: TrendMonth[] }) {
  const [hover, setHover] = useState<number | null>(null);
  const points = months.map((m) => (m.balance === null ? null : Number(m.balance)));
  const known = points.filter((p): p is number => p !== null);
  if (known.length < 2) {
    return <p className="text-sm text-slate-500">Not enough months of data for a balance line yet.</p>;
  }
  const min = Math.min(...known);
  const max = Math.max(...known);
  const span = max - min || 1;
  const plotH = H - PAD.top - PAD.bottom;
  const slot = (W - PAD.left - PAD.right) / months.length;
  const xy = (i: number, v: number) => [
    PAD.left + i * slot + slot / 2,
    PAD.top + (1 - (v - min) / span) * plotH,
  ];

  // Break the line where the balance is unknown rather than drawing across the gap.
  const segments: string[][] = [];
  let current: string[] = [];
  points.forEach((p, i) => {
    if (p === null) {
      if (current.length) segments.push(current);
      current = [];
    } else {
      const [x, y] = xy(i, p);
      current.push(`${x.toFixed(1)},${y.toFixed(1)}`);
    }
  });
  if (current.length) segments.push(current);

  const hovered = hover === null ? null : months[hover];

  return (
    <div className="relative">
      {hovered && hover !== null && hovered.balance !== null && (
        <Tooltip
          index={hover}
          count={months.length}
          title={`${MONTHS[hovered.month - 1]} ${hovered.year}`}
          lines={[["Balance", formatMoney(hovered.balance), BALANCE]]}
        />
      )}
      <table className="sr-only">
        <caption>Total balance at the end of each month</caption>
        <thead>
          <tr><th>Month</th><th>Balance</th></tr>
        </thead>
        <tbody>
          {months.map((m) => (
            <tr key={`${m.year}-${m.month}`}>
              <td>{MONTHS[m.month - 1]} {m.year}</td>
              <td>{m.balance === null ? "no data" : formatMoney(m.balance)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <svg aria-hidden="true" viewBox={`0 0 ${W} ${H}`} className="w-full">
        <line x1={PAD.left} x2={W - PAD.right} y1={H - PAD.bottom} y2={H - PAD.bottom} stroke="#434859" />
        {segments.map((seg, i) => (
          <polyline key={i} points={seg.join(" ")} fill="none" stroke={BALANCE} strokeWidth="2" />
        ))}
        {months.map((m, i) => {
          const p = points[i];
          const [x] = xy(i, 0);
          return (
            <g key={`${m.year}-${m.month}`}>
              {p !== null && (
                <circle cx={xy(i, p)[0]} cy={xy(i, p)[1]} r="3" fill={BALANCE}>
                  <title>{`${MONTHS[m.month - 1]} ${m.year} balance ${formatMoney(m.balance)}`}</title>
                </circle>
              )}
              <rect
                x={x - slot / 2}
                y={PAD.top - 6}
                width={slot}
                height={plotH + 6}
                fill="transparent"
                onMouseEnter={() => setHover(i)}
                onMouseLeave={() => setHover(null)}
              />
              <text x={x} y={H - 8} textAnchor="middle" fontSize="11" fill="#98a1b0">
                {MONTHS[m.month - 1]}
              </text>
            </g>
          );
        })}
      </svg>
      <div className="mt-1 text-xs text-slate-500">
        Month-end balance across accounts, from {compact(min)} to {compact(max)}. A gap means no data
        after the latest statement.
      </div>
    </div>
  );
}
