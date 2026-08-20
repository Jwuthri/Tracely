"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export const STAGES = ["production trace", "failure detection", "regression test", "CI gate"];

const GLYPHS = "!<>-_\\/[]{}=+*^?#01";
const DURATION = 520; // ms a single stage spends resolving
const STAGGER = 200; // ms between one stage starting and the next
const TICK = 40; // ms between re-scrambles — 25fps is plenty for noise

/**
 * `target` with its leading `progress` fraction resolved and the rest replaced by noise.
 * Spaces are never scrambled: they are what keeps the word boundaries legible mid-decode.
 */
export function scramble(target: string, progress: number) {
  const reveal = Math.round(target.length * Math.min(1, Math.max(0, progress)));
  return target
    .split("")
    .map((ch, i) => (i < reveal || ch === " " ? ch : GLYPHS[Math.floor(Math.random() * GLYPHS.length)]))
    .join("");
}

/** Where each stage is at `elapsed` ms into the sequence, 0 → 1. */
export function stageProgress(elapsed: number, index: number) {
  return Math.min(1, Math.max(0, (elapsed - index * STAGGER) / DURATION));
}

export const SEQUENCE_MS = (STAGES.length - 1) * STAGGER + DURATION;

/**
 * The pipeline decodes stage by stage, left to right — the sentence performs the thing it
 * describes. Monospace is load-bearing: every glyph is the same width, so swapping characters
 * every frame cannot reflow the line.
 *
 * ponytail: a setInterval over one elapsed clock, not an animation library. The reference
 * implementation pulled in `motion` purely to tween 0 → 1, which is what `performance.now()` is.
 */
export function ScramblePipeline({ className = "" }: { className?: string }) {
  const [text, setText] = useState<string[]>(STAGES);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  const stop = useCallback(() => {
    if (timer.current) clearInterval(timer.current);
    timer.current = null;
  }, []);

  const run = useCallback(() => {
    if (typeof window === "undefined") return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    stop();
    const t0 = performance.now();
    timer.current = setInterval(() => {
      const elapsed = performance.now() - t0;
      if (elapsed >= SEQUENCE_MS) {
        stop();
        setText(STAGES);
        return;
      }
      setText(STAGES.map((s, i) => scramble(s, stageProgress(elapsed, i))));
    }, TICK);
  }, [stop]);

  // Runs once on mount, timed to land just after the hero's intro has settled.
  useEffect(() => {
    const id = setTimeout(run, 900);
    return () => {
      clearTimeout(id);
      stop();
    };
  }, [run, stop]);

  return (
    <span className={className} onPointerEnter={run}>
      {text.map((stage, i) => (
        <span key={STAGES[i]}>
          {i > 0 && <span className="mx-2 text-signal">→</span>}
          <span className={stage === STAGES[i] ? "text-fg-faint" : "text-signal/80"}>{stage}</span>
        </span>
      ))}
    </span>
  );
}
