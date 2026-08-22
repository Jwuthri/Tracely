import clsx from "clsx";

/** Failure families (`taxonomy` is `"family: detail"`, see domain/failure/signature.py).
 * Colouring by family is the whole point: five clusters rendered in one flat red are
 * indistinguishable, and the first thing you want to know is *what kind* of failure. */
const TONE = {
  execution: { text: "text-fail", bar: "bg-fail", glow: "shadow-[0_0_7px_rgb(var(--c-fail)/0.7)]", chip: "border-fail/25 bg-fail/10 text-fail" },
  output: { text: "text-warn", bar: "bg-warn", glow: "shadow-[0_0_7px_rgb(var(--c-warn)/0.7)]", chip: "border-warn/25 bg-warn/10 text-warn" },
  performance: { text: "text-info", bar: "bg-info", glow: "shadow-[0_0_7px_rgb(var(--c-info)/0.7)]", chip: "border-info/25 bg-info/10 text-info" },
} as const;

export type Tone = (typeof TONE)[keyof typeof TONE];

/** A cluster of 12,000 traces has to fit the same column as one of 9 — "12k" always does.
 * Callers put the exact number in a `title`. */
const COMPACT = new Intl.NumberFormat("en", { notation: "compact", maximumSignificantDigits: 2 });
// Below 1k the exact count fits, and "999" is more use than "1K".
export const compactCount = (n: number) => (n < 1000 ? String(n) : COMPACT.format(n));

/** Taxonomies arrive in two vocabularies: the structural ones are `"family: detail"`
 * (signature.py), the LLM-clustered ones are a free-text category like "tool execution error".
 * Keyword-match the whole string so both land in the same three buckets. */
const KEYWORDS: [RegExp, keyof typeof TONE][] = [
  [/latency|performance|slow|cost/, "performance"],
  [/output|quality|hallucin|answer|format|refus/, "output"],
];

export function clusterTone(taxonomy: string | null | undefined): Tone {
  const t = (taxonomy ?? "").toLowerCase();
  return TONE[KEYWORDS.find(([re]) => re.test(t))?.[1] ?? "execution"];
}

/** The taxonomy as a chip rather than grey text lost at the right edge.
 *
 * The slot is a FIXED width, not the chip's natural one: the chip sits beside a `flex-1` meter,
 * so a longer taxonomy ("tool execution error") stole width from its own meter and every row
 * ended up with a differently-scaled bar. Meters are only worth drawing if they share a
 * baseline across rows. */
export function TaxonomyChip({ taxonomy, tone }: { taxonomy: string; tone: Tone }) {
  return (
    <span className="flex w-[148px] shrink-0 justify-end">
      {taxonomy ? (
        <span
          title={taxonomy}
          className={clsx("truncate rounded border px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider", tone.chip)}
        >
          {taxonomy}
        </span>
      ) : null}
    </span>
  );
}

const SEGMENTS = 20;

/** Counts are printed next to the meter, so the meter's job is rank, not magnitude — and on a
 * linear scale one runaway cluster flattens the rest to a single tick each (1000 vs 9 vs 31 all
 * round to 1/20). Square root keeps the order and keeps the tail readable. */
const scale = (value: number, max: number) => Math.sqrt(value / Math.max(1, max));

/** Share-of-failures meter. Segmented, not a flat bar: two clusters within a few percent of
 * each other draw the same rectangle, but a different number of ticks. */
export function ClusterMeter({ value, max, tone, className }: { value: number; max: number; tone: Tone; className?: string }) {
  const filled = Math.min(SEGMENTS, Math.max(1, Math.round(scale(value, max) * SEGMENTS)));
  return (
    <span className={clsx("flex h-[7px] items-stretch gap-[3px]", className)} aria-hidden>
      {Array.from({ length: SEGMENTS }, (_, i) => (
        <span
          key={i}
          className={clsx(
            "flex-1 rounded-[1.5px] transition-colors",
            i < filled ? tone.bar : "bg-hilite/[0.07]",
            i === filled - 1 && tone.glow,
          )}
        />
      ))}
    </span>
  );
}
