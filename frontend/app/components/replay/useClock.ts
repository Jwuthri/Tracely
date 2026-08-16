"use client";

import { useEffect, useRef, useState } from "react";

/** The shared play clock for the Replay and Fleet views. Advances every animation frame but
 *  COMMITS at ~25fps — a React commit re-renders the whole scene, and 60fps of that is pure
 *  waste when the stage reads identically. */
export function usePlayClock(total: number) {
  const [t, setT] = useState(0);
  const [playing, setPlaying] = useState(true);
  const [speed, setSpeed] = useState(1);
  const raf = useRef<number | null>(null);
  const last = useRef<number>(0);

  useEffect(() => {
    if (!playing || !total) return;
    const COMMIT_MS = 40;
    let pending = 0;
    const tick = (now: number) => {
      // Clamp the frame delta: rAF stops in a hidden tab, and the first frame back would
      // otherwise carry the entire hidden duration — teleporting the play head to the end.
      const dt = Math.min(last.current ? now - last.current : 16, 100);
      last.current = now;
      pending += dt * speed;
      if (pending >= COMMIT_MS) {
        const step = pending;
        pending = 0;
        setT((prev) => {
          const next = prev + step;
          if (next >= total) {
            setPlaying(false);
            return total;
          }
          return next;
        });
      }
      raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);
    return () => {
      if (raf.current) cancelAnimationFrame(raf.current);
      last.current = 0;
    };
  }, [playing, speed, total]);

  const restart = () => {
    setT(0);
    setPlaying(true);
  };
  const seek = (v: number) => {
    setT(v);
    setPlaying(false);
  };
  const toggle = () => (t >= total ? restart() : setPlaying((p) => !p));

  return { t, playing, speed, setSpeed, setT, setPlaying, restart, seek, toggle };
}
