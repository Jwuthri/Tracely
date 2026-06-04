import clsx from "clsx";

export type Bar = { label: string; value: number; sub: number; title?: string };

/** A compact, dependency-free bar chart: each bar's full height is `value`, with the bottom
 *  `sub` portion highlighted (e.g. failures within total traces, or fails within gate runs). */
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
    <div className="flex h-36 items-end gap-2 px-1">
      {data.map((d, i) => {
        const h = Math.max(3, (d.value / max) * 100);
        const subH = d.value ? (d.sub / d.value) * 100 : 0;
        return (
          <div
            key={i}
            className="group flex flex-1 flex-col items-center justify-end"
            title={d.title ?? `${d.label}: ${d.value} (${d.sub})`}
          >
            <span className="mb-1 font-mono text-[10px] tabular-nums text-fg-faint opacity-0 transition-opacity group-hover:opacity-100">
              {d.value}
            </span>
            <div
              className={clsx("relative w-full max-w-[44px] overflow-hidden rounded-t-md transition-all", color)}
              style={{ height: `${h}%` }}
            >
              <div className={clsx("absolute bottom-0 w-full", subColor)} style={{ height: `${subH}%` }} />
            </div>
            <div className="mt-2 font-mono text-[9.5px] text-fg-faint">{d.label}</div>
          </div>
        );
      })}
    </div>
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
