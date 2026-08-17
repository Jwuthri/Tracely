"use client";

import { useEffect, useMemo, useState } from "react";
import { layoutOffice, librarySkills, narrate, poseAt, wallTools } from "@/app/components/replay/office";
import { Bookshelf, CoffeeMachine, Desk, OfficeDoor, PixelPerson, Plant, ToolsRack } from "@/app/components/replay/sprites";
import { OFFICE_PACING, toPlayEvents, type ReplayActor, type ReplayEvent } from "@/app/components/replay/timeline";
import { useWalking } from "@/app/components/replay/useClock";

/* A canned Fleet office for the landing page: the same geometry, sprites and pose engine the
   product runs on (`replay/`), fed one hand-written scene instead of a real trace. Nothing
   here fetches — it is a poster for /sessions/[id]/fleet, not a second implementation. */

export const ACTORS: ReplayActor[] = [
  { id: "support", name: "support_agent", kind: "agent", parent: "", depth: 0, first_ms: 0, last_ms: 7200, events: 4, errors: 0 },
  { id: "orders", name: "order_lookup", kind: "subagent", parent: "support", depth: 1, first_ms: 2600, last_ms: 4700, events: 2, errors: 0 },
  { id: "billing", name: "billing_agent", kind: "subagent", parent: "support", depth: 1, first_ms: 4900, last_ms: 5800, events: 1, errors: 1 },
];

const ev = (e: Partial<ReplayEvent> & { t_ms: number; dur_ms: number; actor: string; kind: string; name: string }): ReplayEvent => ({
  status: "ok", model: "", detail: "", span_id: "", trace_id: "", turn_id: "", station: "desk", ...e,
});

export const SCENE: ReplayEvent[] = [
  ev({ t_ms: 0, dur_ms: 900, actor: "support", kind: "think", name: "plan", detail: "where is my refund?" }),
  ev({ t_ms: 1000, dur_ms: 900, actor: "support", kind: "skill", name: "refund_policy", station: "library" }),
  ev({ t_ms: 2100, dur_ms: 2400, actor: "support", kind: "delegate", name: "order lookup", station: "peer", delegate_to: "orders", say: "pull order #8412", container: true }),
  ev({ t_ms: 2700, dur_ms: 1000, actor: "orders", kind: "tool", name: "search_orders", station: "computer" }),
  ev({ t_ms: 3900, dur_ms: 800, actor: "orders", kind: "llm", name: "answer", detail: "shipped 41 days ago", model: "sonnet" }),
  ev({ t_ms: 4900, dur_ms: 900, actor: "billing", kind: "tool", name: "check_eligibility", station: "computer", status: "error" }),
  ev({ t_ms: 6000, dur_ms: 1200, actor: "support", kind: "llm", name: "reply", detail: "Sure — your refund is on its way!", model: "sonnet" }),
];

const DECLARED = [
  { name: "search_orders", description: "" },
  { name: "check_eligibility", description: "" },
  { name: "issue_refund", description: "" },
  { name: "send_email", description: "" },
];

const HOLD = 2200; // beat of stillness before the scene loops
const FROZEN_T = 3200; // the frame shown when the visitor asked for no motion

const hueOf = (id: string) => {
  let h = 0;
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) >>> 0;
  return h % 360;
};

/** Play clock that loops forever, and stands still for anyone who asked for no motion. */
function useLoopClock(total: number) {
  const [t, setT] = useState(FROZEN_T);
  useEffect(() => {
    if (!total || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    let raf = 0;
    let last = 0;
    let pending = 0;
    setT(0);
    const tick = (now: number) => {
      const dt = Math.min(last ? now - last : 16, 100); // a hidden tab must not teleport the head
      last = now;
      pending += dt;
      if (pending >= 40) {
        setT((p) => (p + pending) % (total + HOLD));
        pending = 0;
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [total]);
  return t;
}

export function FleetPeek() {
  const { events, total } = useMemo(() => toPlayEvents(SCENE, OFFICE_PACING), []);
  const layout = useMemo(() => layoutOffice(ACTORS), []);
  const skills = useMemo(() => librarySkills(events), [events]);
  const tools = useMemo(() => wallTools(events, DECLARED), [events]);
  const t = useLoopClock(total);

  const poses = useMemo(
    () => new Map(ACTORS.map((a, i) => [a.id, poseAt(a, events, t, layout, i)])),
    [events, t, layout],
  );
  const active = [...poses.values()].find((p) => p.working)?.action ?? null;
  const done = t >= total;
  const sign = done
    ? "turn graded · hallucination FAIL → frozen as a case"
    : narrate(events, t, (id) => ACTORS.find((a) => a.id === id)?.name ?? id);

  return (
    <div className="fleet-stage relative aspect-[16/10] select-none overflow-hidden rounded-2xl border border-line shadow-panel">
      {/* wall */}
      <div className="absolute inset-x-0 top-0 h-[17%] border-b-4 border-[#181022] bg-[#2a2138]">
        <div className="absolute left-[6%] top-[22%] h-[52%] w-[9%] rounded-sm border-2 border-[#181022] bg-gradient-to-b from-[#3d4d79] to-[#27304b]" />
        <div className="absolute left-[18%] top-[22%] h-[52%] w-[9%] rounded-sm border-2 border-[#181022] bg-gradient-to-b from-[#3d4d79] to-[#27304b]" />
        <div className="absolute left-1/2 top-1/2 w-[46%] -translate-x-1/2 -translate-y-1/2 rounded border border-[#181022] bg-[#0a0f14] px-3 py-1.5">
          <p className={`truncate text-center font-mono text-[10px] tracking-wider ${done ? "text-fail" : "text-[#57e39a]"}`}>
            {sign}
          </p>
        </div>
        <div className="absolute right-[4%] top-[8%] w-[4.5%]"><OfficeDoor /></div>
      </div>

      {/* floor */}
      <div className="fleet-floor absolute inset-x-0 bottom-0 top-[17%]" />

      {/* fixed furniture */}
      <div className="absolute left-[2%] top-[30%] w-[10%]">
        <Bookshelf skills={skills} active={active?.station === "library" ? active.name : ""} />
      </div>
      <div className="absolute right-[2%] top-[30%] w-[10%]">
        <ToolsRack tools={tools} active={active?.station === "computer" ? active.name : ""} />
      </div>
      <div className="absolute bottom-[4%] left-[3%] w-[5.5%]"><CoffeeMachine /></div>
      <div className="absolute bottom-[6%] right-[8%] w-[3.5%]"><Plant /></div>
      <div className="absolute left-[30%] top-[20%] w-[3.5%]"><Plant /></div>

      {/* desks */}
      {ACTORS.map((a) => {
        const d = layout.desks[a.id];
        const p = poses.get(a.id);
        return (
          <div key={`desk-${a.id}`} className="absolute w-[13%] -translate-x-1/2"
            style={{ left: `${d.x}%`, top: `${d.y + 1.5}%`, zIndex: Math.round(d.y) }}>
            <Desk hue={hueOf(a.id)} on={p?.working === true && p.at === "desk"} name={a.name} />
          </div>
        );
      })}

      {/* characters */}
      {ACTORS.map((a) => {
        const p = poses.get(a.id);
        if (!p) return null;
        return <PeekWalker key={a.id} actor={a} pose={p} />;
      })}

      {done && <div className="fleet-done pointer-events-none absolute inset-0" />}
    </div>
  );
}

function PeekWalker({ actor, pose }: { actor: ReplayActor; pose: ReturnType<typeof poseAt> }) {
  const walking = useWalking(pose.x, pose.y);
  return (
    <div className="absolute -translate-x-1/2 -translate-y-full transition-all duration-700 ease-in-out"
      style={{ left: `${pose.x}%`, top: `${pose.y}%`, zIndex: Math.round(pose.y) + 10 }}>
      {pose.bubble && <PeekBubble bubble={pose.bubble} x={pose.x} y={pose.y} />}
      <PixelPerson hue={hueOf(actor.id)} size={actor.depth ? 34 : 42}
        walking={walking} working={pose.working && !walking} facing={pose.facing} />
      <div className="mx-auto -mt-0.5 h-1.5 w-7 rounded-full bg-black/40 blur-[1.5px]" />
    </div>
  );
}

function PeekBubble({ bubble, x, y }: { bubble: NonNullable<ReturnType<typeof poseAt>["bubble"]>; x: number; y: number }) {
  const anchor = [
    x >= 64 ? "right-0" : x <= 36 ? "left-0" : "left-1/2 -translate-x-1/2",
    y <= 46 ? "top-full mt-1" : "bottom-full mb-2",
  ].join(" ");
  if (bubble.type === "error") {
    return (
      <span className="fleet-pop pointer-events-none absolute bottom-full left-1/2 z-50 mb-1.5 grid h-6 w-6 -translate-x-1/2 animate-bounce place-items-center rounded-full bg-fail font-mono text-[13px] font-bold text-ink-950 shadow-[0_0_14px_rgba(251,113,133,0.8)]">
        !
      </span>
    );
  }
  const skin =
    bubble.type === "thought"
      ? "rounded-[14px] border-t_think/40 bg-ink-800/95 font-mono text-t_think"
      : bubble.type === "speech"
        ? "rounded-lg border-line-bright bg-[#f4f6fb] font-medium text-ink-900"
        : bubble.icon === "skill"
          ? "rounded-md border-t_retriever/50 bg-t_retriever/15 font-mono text-t_retriever"
          : "rounded-md border-t_tool/50 bg-t_tool/15 font-mono text-t_tool";
  const text = bubble.type === "chip" ? `${bubble.icon === "skill" ? "◈" : "⚙"} ${bubble.text}` : bubble.text;
  return (
    <div className={`fleet-pop pointer-events-none absolute z-50 w-max max-w-[190px] ${anchor}`}>
      <div className={`border px-2.5 py-1.5 text-left text-[10px] leading-snug ${skin}`}>{text}</div>
    </div>
  );
}
