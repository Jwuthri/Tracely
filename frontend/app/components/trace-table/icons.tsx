// Inline SVG icons used by the trace table. Lucide-shaped, 24x24, currentColor — kept local to the
// table because they're table-specific shapes (chevrons, run, attachment glyphs) rather than reusable
// app-wide icons. Same `svg()` helper as the source module, so weights/joins stay consistent.
import type { SVGProps } from "react";

export const svg = (p: SVGProps<SVGSVGElement>) => ({
  xmlns: "http://www.w3.org/2000/svg",
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 2,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  ...p,
});

export const ChevronR = (p: SVGProps<SVGSVGElement>) => <svg {...svg(p)}><path d="m9 18 6-6-6-6" /></svg>;

export const Play = (p: SVGProps<SVGSVGElement>) => (
  <svg {...svg(p)}><path d="M5 5a2 2 0 0 1 3.008-1.728l11.997 6.998a2 2 0 0 1 .003 3.458l-12 7A2 2 0 0 1 5 19z" /></svg>
);

export const Bot = (p: SVGProps<SVGSVGElement>) => (
  <svg {...svg(p)}>
    <path d="M12 8V4H8" /><rect width="16" height="12" x="4" y="8" rx="2" />
    <path d="M2 14h2" /><path d="M20 14h2" /><path d="M15 13v2" /><path d="M9 13v2" />
  </svg>
);

export const ChevronsUpDown = (p: SVGProps<SVGSVGElement>) => (
  <svg {...svg(p)}><path d="m7 15 5 5 5-5" /><path d="m7 9 5-5 5 5" /></svg>
);

export const Eye = (p: SVGProps<SVGSVGElement>) => (
  <svg {...svg(p)}>
    <path d="M2.062 12.348a1 1 0 0 1 0-.696 10.75 10.75 0 0 1 19.876 0 1 1 0 0 1 0 .696 10.75 10.75 0 0 1-19.876 0" />
    <circle cx="12" cy="12" r="3" />
  </svg>
);

export const ImageIcon = (p: SVGProps<SVGSVGElement>) => (
  <svg {...svg(p)}><rect width="18" height="18" x="3" y="3" rx="2" ry="2" /><circle cx="9" cy="9" r="2" /><path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21" /></svg>
);

export const FileIcon = (p: SVGProps<SVGSVGElement>) => (
  <svg {...svg(p)}><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><path d="M14 2v6h6" /></svg>
);

export const FilterIcon = (p: SVGProps<SVGSVGElement>) => (
  <svg {...svg(p)}><path d="M22 3H2l8 9.46V19l4 2v-8.54z" /></svg>
);

export const PlusIcon = (p: SVGProps<SVGSVGElement>) => (
  <svg {...svg(p)}><path d="M5 12h14" /><path d="M12 5v14" /></svg>
);

export const DotsIcon = (p: SVGProps<SVGSVGElement>) => (
  <svg {...svg(p)}><circle cx="12" cy="12" r="1" /><circle cx="12" cy="5" r="1" /><circle cx="12" cy="19" r="1" /></svg>
);

// Compact chat-bubble + arrow-out + text-lines glyphs used by content pills.
export const ChatGlyph = (p: SVGProps<SVGSVGElement>) => (
  <svg {...svg(p)}><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" /></svg>
);

export const ExternalLink = (p: SVGProps<SVGSVGElement>) => (
  <svg {...svg(p)}><path d="M15 3h6v6" /><path d="M10 14 21 3" /><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" /></svg>
);

export const TextGlyph = (p: SVGProps<SVGSVGElement>) => (
  <svg {...svg(p)}><path d="M4 6h16M4 12h16M4 18h10" /></svg>
);
