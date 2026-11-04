"use client";

/** A tiny line of month-end balances. Drawing only: the numbers are never shown from here. */
export function Sparkline({
  values,
  label,
  width = 120,
  height = 28,
}: {
  values: number[];
  label: string;
  width?: number;
  height?: number;
}) {
  if (values.length < 2) return null;
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const span = hi - lo || 1;
  const step = width / (values.length - 1);
  const points = values
    .map((v, i) => `${(i * step).toFixed(1)},${(height - 2 - ((v - lo) / span) * (height - 4)).toFixed(1)}`)
    .join(" ");
  const last = values[values.length - 1];
  const lastY = height - 2 - ((last - lo) / span) * (height - 4);
  return (
    <svg role="img" aria-label={label} width={width} height={height} viewBox={`0 0 ${width} ${height}`}>
      <polyline points={points} fill="none" stroke="currentColor" strokeWidth="1.5" className="text-accent" />
      <circle cx={width} cy={lastY} r="2" className="fill-current text-accent" />
    </svg>
  );
}
