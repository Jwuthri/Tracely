import clsx from "clsx";

/** How many of `segments` are lit for a 0–100 value. */
export function lit(value: number, segments: number) {
  return Math.round((Math.max(0, Math.min(100, value)) / 100) * segments);
}

/** Segmented gauge — a bar chart of one value. Reads better than a smooth fill when the number
 *  is a budget being spent down, because the discrete notches make "how much is left" countable.
 *  `tone` is the caller's bg class so each call site keeps its own threshold story. */
export function Meter({
  value,
  segments = 10,
  tone = "bg-signal/60",
  className,
}: {
  value: number;
  segments?: number;
  tone?: string;
  className?: string;
}) {
  const on = lit(value, segments);
  return (
    <div className={clsx("flex gap-[3px]", className)} role="meter" aria-valuenow={Math.round(value)}>
      {Array.from({ length: segments }, (_, i) => (
        <div
          key={i}
          className={clsx("h-2.5 flex-1 rounded-[2px] transition-colors", i < on ? tone : "bg-ink-900")}
        />
      ))}
    </div>
  );
}
