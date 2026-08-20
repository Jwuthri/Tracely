"use client";

import { useEffect, useState } from "react";

/* The write path as one drawing: trace → span events → evaluators → failures / cases / gates.
   Two callers, one component:
     · no props — the canned story, for the marketing landing.
     · `live={…}` — this workspace's real counts, in the first-run card. A stage with nothing in
       it is dim and its wire carries no traffic, so the picture shows where the loop stops.

   ponytail: no framer-motion. The travelling dots are SMIL (<animateMotion>), the pulses are the
   `pulse2` keyframe from tailwind.config.ts, the log line is a keyed remount + `fadeup`. */

export type PipelineCounts = {
  traces: number;
  evaluators: number;
  failures: number;
  clusters: number;
  cases: number;
  gates: number;
};

type Stage = { eyebrow: string; title: string; sub: string; lit: boolean };
type Out = { label: string; tone: string; lit: boolean };

const n = (v: number) => v.toLocaleString("en-US");

/** Captions, lit-ness and header status. Pure, so the empty / partial / closed shapes are testable. */
export function shape(live?: PipelineCounts): { stages: Stage[]; outs: Out[]; status: string } {
  if (!live) {
    return {
      stages: [
        { eyebrow: "PRODUCTION", title: "Agent trace", sub: "sdk · otlp", lit: true },
        { eyebrow: "STORE", title: "Span events", sub: "blob → clickhouse", lit: true },
        { eyebrow: "EVALUATORS", title: "Grading", sub: "judge + structural", lit: true },
      ],
      outs: [
        { label: "Trace verdict", tone: "fill-ok", lit: true },
        { label: "Failure cluster", tone: "fill-warn", lit: true },
        { label: "PR gate · blocked", tone: "fill-fail", lit: true },
      ],
      status: "4 evaluators · 1 fail",
    };
  }
  // A raw execution error is clustered without any evaluator scoring it FAIL, so both count as
  // "caught" — same rule as the activation checklist.
  const caught = live.failures || live.clusters;
  return {
    stages: [
      { eyebrow: "PRODUCTION", title: "Agent trace", sub: live.traces ? `${n(live.traces)} traces` : "none yet", lit: live.traces > 0 },
      { eyebrow: "STORE", title: "Span events", sub: "blob → clickhouse", lit: live.traces > 0 },
      { eyebrow: "EVALUATORS", title: "Grading", sub: live.evaluators ? `${n(live.evaluators)} columns` : "none yet", lit: live.evaluators > 0 },
    ],
    outs: [
      { label: caught ? `${n(caught)} caught` : "Failures", tone: caught ? "fill-ok" : "fill-line", lit: caught > 0 },
      { label: live.cases ? `${n(live.cases)} case${live.cases === 1 ? "" : "s"}` : "Regression cases", tone: live.cases ? "fill-ok" : "fill-line", lit: live.cases > 0 },
      { label: live.gates ? `${n(live.gates)} gate run${live.gates === 1 ? "" : "s"}` : "PR gate", tone: live.gates ? "fill-ok" : "fill-line", lit: live.gates > 0 },
    ],
    status: `${n(live.traces)} traces · ${n(live.evaluators)} evaluators`,
  };
}

const LOG = [
  "POST /v1/traces — 3 spans · agent support_bot",
  "blob stored → s3://traces/8f2c… (durable first)",
  "clickhouse: 3 events written · ReplacingMergeTree",
  "evaluate_run_task queued · countdown 4s for late spans",
  "grading with 4 evaluators — 3 structural, 1 llm judge",
  "FAIL tool_contract — refund issued, eligibility never checked",
  'clustered into "refund without eligibility" · 12 traces',
  "case frozen from trace 8f2c… → hermetic replay bundle",
  "gate on PR #214 — 1 case failing · commit status red",
  "idle. listening for the next trace…",
];

/** x,y of each output box, and the wire that feeds it. */
const OUT_Y = [35, 73, 111];
const WIRES = [
  "M116,88 L158,88",
  "M268,88 L306,88",
  "M411,88 C425,88 435,50 448,50",
  "M411,88 L448,88",
  "M411,88 C425,88 435,126 448,126",
];

/** Dots travelling a wire. Rendered only when the visitor hasn't asked for stillness. */
function Flow({ path, dur, delay, r, opacity }: { path: string; dur: number; delay: number; r: number; opacity: number }) {
  return (
    <circle r={r} className="fill-signal" opacity={opacity}>
      <animateMotion dur={`${dur}s`} repeatCount="indefinite" begin={`${delay}s`} path={path} />
    </circle>
  );
}

function Node({ x, y, w, h, stage }: { x: number; y: number; w: number; h: number; stage: Stage }) {
  const cx = x + w / 2;
  return (
    <g>
      <rect x={x} y={y} width={w} height={h} rx="8" className={`fill-ink-800 ${stage.lit ? "stroke-line" : "stroke-line/50"}`} strokeWidth="1" />
      <text x={cx} y={y + 17} textAnchor="middle" fontSize="9.5" letterSpacing=".07em" className="fill-fg-faint">
        {stage.eyebrow}
      </text>
      <text x={cx} y={y + 34} textAnchor="middle" fontSize="12" className={stage.lit ? "fill-fg" : "fill-fg-faint"}>
        {stage.title}
      </text>
      <text x={cx} y={y + 56} textAnchor="middle" fontSize="8.5" fontFamily="monospace" className="fill-fg-faint/70">
        {stage.sub}
      </text>
    </g>
  );
}

export function PipelinePeek({ live }: { live?: PipelineCounts }) {
  const { stages, outs, status } = shape(live);
  const [i, setI] = useState(0);
  const [traces, setTraces] = useState(1247);
  const [motion, setMotion] = useState(false);

  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    setMotion(true);
    if (live) return; // the live card has no rolling log or ticking counter to drive
    const log = setInterval(() => setI((p) => (p + 1) % LOG.length), 2700);
    const count = setInterval(() => setTraces((p) => p + 1), 7200);
    return () => {
      clearInterval(log);
      clearInterval(count);
    };
  }, [live]);

  const pulse = motion ? "animate-pulse2" : "";
  const flowing = [stages[0].lit, stages[2].lit, outs[0].lit, outs[1].lit, outs[2].lit];
  const judgeLit = stages[2].lit;

  return (
    <div className="mx-auto w-full max-w-[640px] overflow-hidden rounded-2xl border border-line bg-ink-900 shadow-frame">
      <div className="flex items-center justify-between border-b border-line px-[18px] py-[11px]">
        <div className="flex items-center gap-2">
          <span className={`inline-block h-1.5 w-1.5 rounded-full ${stages[0].lit ? `bg-ok ${pulse}` : "bg-line"}`} />
          <span className="font-mono text-[10px] tracking-[0.1em] text-fg-faint">INGEST → EVAL → GATE</span>
        </div>
        <span className="font-mono text-[10px] text-fg-faint/70">{status}</span>
      </div>

      <svg
        width="100%"
        viewBox="0 0 580 172"
        className="block"
        role="img"
        aria-label={`A trace flows into span storage, is graded by evaluators, and fans out into ${outs.map((o) => o.label).join(", ")}.`}
      >
        <defs>
          <marker id="pp-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto">
            <path d="M2 1.5L7.5 5L2 8.5" fill="none" className="stroke-signal/50" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
          </marker>
        </defs>

        {WIRES.map((d, w) => (
          <path
            key={d}
            d={d}
            fill="none"
            className={flowing[w] ? (w < 2 ? "stroke-signal/25" : "stroke-signal/15") : "stroke-line/60"}
            strokeWidth="1.5"
            strokeDasharray="3 5"
            markerEnd={w < 2 ? "url(#pp-arrow)" : undefined}
          />
        ))}

        {motion &&
          WIRES.map((d, w) =>
            flowing[w] ? <Flow key={d} path={d} dur={1.05 + w * 0.09} delay={w * 0.18} r={2.4} opacity={0.95} /> : null,
          )}

        <Node x={16} y={66} w={100} h={44} stage={stages[0]} />
        <Node x={158} y={66} w={110} h={44} stage={stages[1]} />

        {/* the evaluators — the one node that is doing work, so the only one that is lit */}
        <rect
          x="306"
          y="53"
          width="105"
          height="70"
          rx="10"
          className={judgeLit ? "fill-signal-deep stroke-signal" : "fill-ink-800 stroke-line/50"}
          strokeWidth="1"
        />
        <text x="358" y="78" textAnchor="middle" fontSize="9.5" letterSpacing=".07em" className={judgeLit ? "fill-signal/80" : "fill-fg-faint"}>
          {stages[2].eyebrow}
        </text>
        <text x="358" y="97" textAnchor="middle" fontSize="13" fontWeight="500" className={judgeLit ? "fill-fg" : "fill-fg-faint"}>
          {stages[2].title}
        </text>
        {[346, 358, 370].map((cx, k) => (
          <circle
            key={cx}
            cx={cx}
            cy="113"
            r="2.8"
            className={judgeLit ? `fill-signal ${pulse}` : "fill-line"}
            style={{ animationDelay: `${k * 0.4}s`, animationDuration: "1.2s" }}
          />
        ))}
        <text x="358" y="139" textAnchor="middle" fontSize="8.5" fontFamily="monospace" className={judgeLit ? "fill-signal/60" : "fill-fg-faint/70"}>
          {stages[2].sub}
        </text>

        {outs.map((o, k) => (
          <g key={o.label}>
            <rect x="448" y={OUT_Y[k]} width="116" height="30" rx="7" className={`fill-ink-900 ${o.lit ? "stroke-line" : "stroke-line/50"}`} strokeWidth="1" />
            <text x="498" y={OUT_Y[k] + 18.5} textAnchor="middle" fontSize="11" className={o.lit ? "fill-fg-muted" : "fill-fg-faint"}>
              {o.label}
            </text>
            <circle cx="550" cy={OUT_Y[k] + 8} r="3" className={`${o.tone} ${o.lit && o.tone !== "fill-ok" ? pulse : ""}`} style={{ animationDelay: `${k * 0.35}s` }} />
          </g>
        ))}
      </svg>

      {!live && (
        <>
          <div className="h-[52px] border-t border-line px-[18px] py-[9px]">
            <div className="flex h-full items-start gap-2">
              <span className="shrink-0 font-mono text-[13px] leading-[1.5] text-signal/60">›</span>
              <p key={i} className="animate-fadeup font-mono text-[11px] leading-[1.55] text-fg-muted">
                {LOG[i]}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-[22px] border-t border-line px-[18px] py-[10px]">
            {[
              ["TRACES", traces.toLocaleString()],
              ["SPANS", "4.2M"],
              ["INGEST P50", "48ms"],
            ].map(([k, v]) => (
              <div key={k}>
                <div className="mb-[3px] text-[9px] tracking-[0.09em] text-fg-faint">{k}</div>
                <div className="font-mono text-[16px] text-fg-muted">{v}</div>
              </div>
            ))}
            <div className="ml-auto text-right">
              <div className="mb-[3px] text-[9px] tracking-[0.09em] text-fg-faint">STACK</div>
              <div className="font-mono text-[10px] text-signal/70">OTLP · ClickHouse</div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
