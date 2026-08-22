import clsx from "clsx";
import { DOCS_URL } from "@/app/lib/site";

/** "Docs ↗" pill that sits next to a page or panel title — every feature points at the page
 *  that explains how it works. `path` is the docs-site path (e.g. `/product/trends#cross-metric-analysis`). */
export function DocLink({ path, className }: { path: string; className?: string }) {
  return (
    <a
      href={`${DOCS_URL}${path}`}
      target="_blank"
      rel="noreferrer"
      title="Open the documentation for this feature"
      className={clsx(
        "inline-flex shrink-0 items-center gap-1 rounded-md border border-line px-2 py-[3px] font-mono text-[10.5px] font-medium uppercase tracking-wide text-fg-faint transition-colors hover:border-signal/40 hover:text-signal",
        className,
      )}
    >
      Docs
      <span aria-hidden>↗</span>
    </a>
  );
}
