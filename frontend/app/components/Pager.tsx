import clsx from "clsx";

/** Prev/next links for a server-rendered list page.
 *
 *  ponytail: plain links, no client state — the page number lives in the URL, so the back button
 *  works, a page is shareable, and the list stays a server component (no hydration cost for what
 *  is a table of text). Same trade the clusters page already made for its `min_size` filter.
 *
 *  Renders nothing when everything fits on one page. */
export function Pager({
  page,
  pageSize,
  total,
  href,
  label = "rows",
}: {
  page: number; // 1-based
  pageSize: number;
  total: number;
  /** Builds the URL for a page — keeps whatever other params the page already carries. */
  href: (page: number) => string;
  label?: string;
}) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  // Hidden when everything fits — but never when the URL points past the end, or a stale
  // `?page=3` link would strand you on an empty list with no way back.
  if (total <= pageSize && page <= 1) return null;
  const first = (page - 1) * pageSize + 1;
  const last = Math.min(page * pageSize, total);
  // `first > total` is the stale-link case above: there is no range to name, so say that instead
  // of rendering a backwards one ("26–0 of 0").
  const range =
    total === 0
      ? `no ${label}`
      : first > total
        ? `page ${page} is past the end · ${total} ${label}`
        : `${first}–${last} of ${total} ${label}`;
  const link =
    "rounded-lg border border-line bg-ink-800 px-3 py-1.5 text-[12.5px] font-medium text-fg-muted transition-colors hover:text-fg";
  const dead = "pointer-events-none opacity-40";

  return (
    <nav
      aria-label={`${label} pagination`}
      className="flex items-center justify-between gap-3 px-1 pt-1"
    >
      <span className="font-mono text-[10.5px] text-fg-faint">{range}</span>
      <span className="flex items-center gap-2">
        <a
          href={href(page - 1)}
          aria-disabled={page <= 1}
          className={clsx(link, page <= 1 && dead)}
        >
          ← Prev
        </a>
        <span className="font-mono text-[10.5px] text-fg-faint">
          {page} / {pages}
        </span>
        <a
          href={href(page + 1)}
          aria-disabled={page >= pages}
          className={clsx(link, page >= pages && dead)}
        >
          Next →
        </a>
      </span>
    </nav>
  );
}

/** 1-based page number from a `?page=` search param, clamped to something sane. */
export function pageParam(raw: string | undefined): number {
  const n = Number(raw);
  return Number.isFinite(n) && n >= 1 ? Math.floor(n) : 1;
}
