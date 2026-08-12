import { ImageResponse } from "next/og";

// The social card every link preview renders — Twitter/X, LinkedIn, Slack, Discord. Lives at the
// app root so every route inherits it. Colors are the tailwind.config.ts tokens by hand: satori
// parses inline styles only, so there is no Tailwind here and nothing to keep in sync but these
// five hex values.
// ponytail: no custom font — satori's bundled sans is close enough, and loading Bricolage
// Grotesque would put a network fetch (or a checked-in .ttf) in the build path. Ship the font when
// the card becomes a brand surface, not before.

export const alt = "Tracely — LLM observability and AI agent evaluation in CI";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

const INK = "#05070c";
const SIGNAL = "#22d3ee";
const FG = "#e8ebf2";
const MUTED = "#9aa3b6";
const LINE = "#1b2230";

export default function OpengraphImage() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          background: INK,
          backgroundImage: `radial-gradient(900px 480px at 50% -20%, rgba(34,211,238,0.20), transparent 70%)`,
          padding: 72,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 20 }}>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              width: 68,
              height: 68,
              borderRadius: 22,
              border: `1px solid rgba(34,211,238,0.35)`,
              background: "rgba(34,211,238,0.10)",
            }}
          >
            <svg width="34" height="34" viewBox="0 0 24 24" fill="none">
              <path d="M12 2 22 12 12 22 2 12Z" stroke={SIGNAL} strokeWidth="1.8" strokeLinejoin="round" />
              <circle cx="12" cy="12" r="2.7" fill={SIGNAL} />
            </svg>
          </div>
          <div style={{ display: "flex", fontSize: 40, fontWeight: 700, color: FG, letterSpacing: -1 }}>Tracely</div>
        </div>

        <div style={{ display: "flex", flexDirection: "column" }}>
          <div style={{ display: "flex", fontSize: 76, fontWeight: 800, color: FG, letterSpacing: -2.5, lineHeight: 1.05 }}>
            Production failures
          </div>
          <div style={{ display: "flex", fontSize: 76, fontWeight: 800, color: SIGNAL, letterSpacing: -2.5, lineHeight: 1.05 }}>
            become regression tests.
          </div>
          <div style={{ display: "flex", marginTop: 28, fontSize: 27, color: MUTED, lineHeight: 1.4, maxWidth: 940 }}>
            LLM observability and agent evaluation that gates your CI — grade every trace, cluster the
            failures, replay them on every pull request.
          </div>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 16, borderTop: `1px solid ${LINE}`, paddingTop: 28 }}>
          {["production trace", "failure detection", "regression test", "CI gate"].map((step, i) => (
            <div key={step} style={{ display: "flex", alignItems: "center", gap: 16 }}>
              {i > 0 && <div style={{ display: "flex", fontSize: 24, color: SIGNAL }}>→</div>}
              <div style={{ display: "flex", fontSize: 24, color: MUTED }}>{step}</div>
            </div>
          ))}
        </div>
      </div>
    ),
    size
  );
}
