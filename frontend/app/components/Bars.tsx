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
