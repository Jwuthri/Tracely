import clsx from "clsx";

export type Bar = { label: string; value: number; sub: number; title?: string };

/** A compact, dependency-free bar chart: each bar's full height is `value`, with the bottom
 *  `sub` portion highlighted (e.g. failures within total traces, or fails within gate runs).
 *  Bars are direct children of a fixed-height track so their % heights resolve correctly. */
export function Bars({
  data,
  color,
  subColor,
}: {
  data: Bar[];
  color: string; // tailwind bg class for the total bar
  subColor: string; // tailwind bg class for the highlighted (bottom) portion
}) {
  if (data.length === 0) {
    return <div className="grid h-36 place-items-center text-[12px] text-fg-faint">No data in this window yet.</div>;
  }
  const max = Math.max(1, ...data.map((d) => d.value));
  return (
    <div>
      <div className="flex h-32 items-end gap-2">
        {data.map((d, i) => {
          const h = d.value ? Math.max(4, (d.value / max) * 100) : 1;
          const subH = d.value ? (d.sub / d.value) * 100 : 0;
          return (
            <div
              key={i}
              className={clsx("relative flex-1 overflow-hidden rounded-t-md", color)}
              style={{ height: `${h}%`, maxWidth: 56 }}
              title={d.title ?? `${d.label}: ${d.value} (${d.sub})`}
            >
              <div className={clsx("absolute bottom-0 w-full", subColor)} style={{ height: `${subH}%` }} />
            </div>
          );
        })}
      </div>
      <div className="mt-2 flex gap-2">
        {data.map((d, i) => (
          <div key={i} className="flex-1 text-center font-mono text-[9.5px] text-fg-faint" style={{ maxWidth: 56 }}>
            {d.label}
          </div>
        ))}
      </div>
    </div>
  );
}

/** Map a series to `x,y` points in a 100x100 viewBox (y flipped: 0 = top). `max` is shared
 *  across series so overlaid lines stay comparable; a flat/empty series pins to the baseline. */
export function sparkPoints(values: number[], max: number): string {
  if (values.length === 0) return "";
  const top = max > 0 ? max : 1;
  // A single sample is drawn edge-to-edge as a flat line — a one-point polyline renders nothing,
  // which reads as "no data" on a fresh project that has exactly one day of traces.
  const pts = values.length === 1 ? [values[0], values[0]] : values;
  const step = 100 / (pts.length - 1);
  return pts
    .map((v, i) => `${(i * step).toFixed(2)},${(100 - (Math.max(0, v) / top) * 100).toFixed(2)}`)
    .join(" ");
}

export type Series = { values: number[]; stroke: string; fill?: string; label: string };

/** Multi-series line chart in pure SVG — no chart dependency. `preserveAspectRatio="none"`
 *  stretches the 100x100 viewBox to the box, so stroke widths are set in viewBox units and
 *  `vector-effect` keeps them 1px on screen regardless of the stretch. */
export function Spark({
  series,
  height = 120,
  grid = true,
}: {
  series: Series[];
  height?: number;
  grid?: boolean; // off for the inline sparklines in stat cards, where rules are just noise
}) {
  const max = Math.max(1, ...series.flatMap((s) => s.values));
  if (series.every((s) => s.values.length === 0)) {
    return <div className="grid place-items-center text-[12px] text-fg-faint" style={{ height }}>No data in this window yet.</div>;
  }
  return (
    <svg viewBox="0 0 100 100" preserveAspectRatio="none" style={{ height }} className="w-full overflow-visible">
      {grid && [0, 50, 100].map((y) => (
        <line key={y} x1="0" y1={y} x2="100" y2={y} className="stroke-line" strokeWidth="0.5" vectorEffect="non-scaling-stroke" />
      ))}
      {series.map((s, i) => {
        const pts = sparkPoints(s.values, max);
        return (
          <g key={i}>
            {s.fill && <polygon points={`0,100 ${pts} 100,100`} className={s.fill} />}
            <polyline points={pts} fill="none" className={s.stroke} strokeWidth="1.5"
              strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
          </g>
        );
      })}
    </svg>
  );
}

export function Legend({ items }: { items: [string, string][] }) {
  return (
    <div className="mt-4 flex items-center gap-4">
      {items.map(([cls, label], i) => (
        <span key={i} className="flex items-center gap-1.5 font-mono text-[10.5px] text-fg-faint">
          <span className={clsx("h-2.5 w-2.5 rounded-sm", cls)} /> {label}
        </span>
      ))}
    </div>
  );
}
