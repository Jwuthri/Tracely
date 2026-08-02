"use client";

import clsx from "clsx";
import { useState } from "react";
import type { ConvNode, FullTurn } from "../lib/api";
import { LEVELS, type EvalLevel } from "./eval-levels";
import { SessionView } from "./SessionView";

type Level = { key: EvalLevel; conv: ConvNode; turns: FullTurn[] };

/** One tab per level, each showing every run at it — batch and sequential columns together, since
 *  the mode is how a column runs, not what it grades. Which column produced a row is the Agent
 *  cell. Levels that graded nothing are not offered: an empty tab reads as "this failed". */
export function EvalLevelView({ levels }: { levels: Level[] }) {
  const [active, setActive] = useState<EvalLevel>(levels[0].key);
  const shown = levels.find((l) => l.key === active) ?? levels[0];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-1.5">
        {LEVELS.filter((l) => levels.some((x) => x.key === l.key)).map((l) => {
          const level = levels.find((x) => x.key === l.key)!;
          return (
            <button
              key={l.key}
              onClick={() => setActive(l.key)}
              title={l.hint}
              className={clsx(
                "rounded-lg border px-3 py-1.5 text-[12px] font-medium transition-colors",
                active === l.key
                  ? "border-info/50 bg-info/15 text-info"
                  : "border-line bg-ink-800 text-fg-muted hover:text-fg",
              )}
            >
              {l.label}
              <span className="ml-1.5 font-mono text-[10.5px] opacity-70">{level.turns.length}</span>
            </button>
          );
        })}
      </div>

      <p className="text-[12.5px] text-fg-faint">{LEVELS.find((l) => l.key === active)?.hint}</p>

      <SessionView key={shown.key} conv={shown.conv} turns={shown.turns} />
    </div>
  );
}
