/* Pixel-art office furniture + characters, all inline SVG (no assets, no licenses).
   Everything uses shape-rendering: crispEdges so rectangles stay pixel-sharp at any scale. */

const crisp = { shapeRendering: "crispEdges" as const };

/** A little person. Hue drives shirt + hair so every agent is recognizable at a glance. */
export function PixelPerson({
  hue,
  size = 44,
  walking = false,
  working = false,
  facing = 1,
  dim = false,
  hat = false,
}: {
  hue: number;
  size?: number;
  walking?: boolean;
  working?: boolean;
  facing?: 1 | -1;
  dim?: boolean;
  /** A beanie: the customer, not staff. */
  hat?: boolean;
}) {
  const shirt = `hsl(${hue} 62% 52%)`;
  const shirtDark = `hsl(${hue} 62% 40%)`;
  const hair = `hsl(${(hue + 160) % 360} 38% 28%)`;
  return (
    <div
      className={walking ? "fleet-walk" : working ? "fleet-type" : "fleet-breathe"}
      style={{ width: size, height: size * 1.18, transform: `scaleX(${facing})`, filter: dim ? "grayscale(0.9) brightness(0.7)" : undefined }}
    >
      <svg viewBox="0 0 36 43" width="100%" height="100%" style={crisp} aria-hidden>
        {/* hair + head */}
        <rect x="10" y="0" width="16" height="5" fill={hair} />
        <rect x="8" y="2" width="4" height="6" fill={hair} />
        <rect x="10" y="4" width="16" height="10" fill="hsl(28 56% 74%)" />
        {hat && <rect x="8" y="0" width="20" height="6" fill="#e8b04b" />}
        {hat && <rect x="8" y="4" width="20" height="2" fill="#b8843a" />}
        <rect x="14" y="8" width="3" height="3" fill="#151a24" />
        <rect x="21" y="8" width="3" height="3" fill="#151a24" />
        {/* body */}
        <rect x="8" y="15" width="20" height="13" rx="1" fill={shirt} />
        <rect x="8" y="24" width="20" height="4" fill={shirtDark} />
        {/* arms */}
        <rect className="fleet-arm-l" x="4" y="16" width="4" height="9" fill={shirt} />
        <rect className="fleet-arm-r" x="28" y="16" width="4" height="9" fill={shirt} />
        {/* legs */}
        <rect className="fleet-leg-l" x="11" y="28" width="5" height="11" fill="#232b3d" />
        <rect className="fleet-leg-r" x="20" y="28" width="5" height="11" fill="#232b3d" />
        <rect className="fleet-leg-l" x="10" y="39" width="6" height="3" fill="#0d1017" />
        <rect className="fleet-leg-r" x="20" y="39" width="6" height="3" fill="#0d1017" />
      </svg>
    </div>
  );
}

/** A desk with a monitor whose screen lights up in the owner's hue while they work. */
export function Desk({ hue, on, name }: { hue: number; on: boolean; name: string }) {
  return (
    <div className="flex flex-col items-center">
      <svg viewBox="0 0 92 46" width="100%" style={crisp} aria-hidden>
        {/* monitor */}
        <rect x="30" y="0" width="30" height="20" rx="2" fill="#10151f" stroke="#2a3348" strokeWidth="1.4" />
        <rect x="33" y="3" width="24" height="14" fill={on ? `hsl(${hue} 80% 62% / 0.85)` : "#182031"} className={on ? "fleet-screen" : undefined} />
        <rect x="42" y="20" width="6" height="4" fill="#2a3348" />
        {/* desktop */}
        <rect x="2" y="24" width="88" height="7" rx="2" fill="#8a5a33" />
        <rect x="2" y="29" width="88" height="3" fill="#6d4526" />
        {/* keyboard + mug */}
        <rect x="38" y="25" width="16" height="3" rx="1" fill="#39435c" />
        <rect x="70" y="21" width="7" height="6" rx="1" fill={`hsl(${hue} 60% 55%)`} />
        {/* legs */}
        <rect x="6" y="32" width="5" height="13" fill="#5d3a1f" />
        <rect x="81" y="32" width="5" height="13" fill="#5d3a1f" />
      </svg>
      <span className="mt-0.5 rounded-sm bg-ink-950/85 px-1.5 py-px font-mono text-[9px] text-fg-muted">
        {name}
      </span>
    </div>
  );
}

/** The skill library: one book spine per skill; the active one slides out and glows. */
export function Bookshelf({ skills, active, onPick }: {
  skills: string[]; active: string; onPick?: (name: string) => void;
}) {
  const spineHue = (s: string) => {
    let h = 0;
    for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
    return h % 360;
  };
  const shelves: string[][] = [[], [], []];
  skills.slice(0, 12).forEach((s, i) => shelves[i % 3].push(s));
  return (
    <div className="flex flex-col items-center">
      <svg viewBox="0 0 74 110" width="100%" style={crisp} aria-hidden={onPick ? undefined : true}>
        <rect x="0" y="0" width="74" height="110" rx="2" fill="#4a2f18" />
        <rect x="4" y="4" width="66" height="102" fill="#2c1b0d" />
        {shelves.map((row, si) => (
          <g key={si}>
            <rect x="4" y={36 + si * 32} width="66" height="4" fill="#5d3a1f" />
            {row.map((s, bi) => {
              const isActive = s === active;
              return (
                <g key={s} role={onPick ? "button" : undefined} onClick={() => onPick?.(s)}
                  className={onPick ? "cursor-pointer hover:brightness-150" : undefined}>
                  <title>{s}</title>
                  <rect
                    x={8 + bi * 13}
                    y={isActive ? 8 + si * 32 : 12 + si * 32}
                    width="10"
                    height="24"
                    rx="1"
                    fill={`hsl(${spineHue(s)} 55% ${isActive ? 62 : 45}%)`}
                    className={isActive ? "fleet-book" : undefined}
                  />
                </g>
              );
            })}
          </g>
        ))}
      </svg>
      <span className="mt-1 font-mono text-[9px] uppercase tracking-[0.2em] text-fg-faint">library</span>
    </div>
  );
}

/** The tool wall: a rack with one LED slot per tool. Running one lights it up; tools that
 *  ran keep a warm LED, declared-but-never-run ones stay visibly dark — the wall must not
 *  present the catalog as activity. */
export function ToolsRack({ tools, active, onPick }: {
  tools: { name: string; used: boolean }[]; active: string; onPick?: (name: string) => void;
}) {
  return (
    <div className="flex flex-col items-center">
      <svg viewBox="0 0 74 110" width="100%" style={crisp} aria-hidden={onPick ? undefined : true}>
        <rect x="0" y="0" width="74" height="110" rx="2" fill="#1c2434" />
        <rect x="4" y="4" width="66" height="102" fill="#12192a" />
        {tools.slice(0, 8).map((t, i) => {
          const isActive = t.name === active;
          const led = isActive ? "#34d399" : t.used ? "#1f6f52" : "#26314a";
          const label = isActive ? "#7df0ff" : t.used ? "#39435c" : "#232c42";
          return (
            <g key={t.name} opacity={t.used || isActive ? 1 : 0.55}
              role={onPick ? "button" : undefined} onClick={() => onPick?.(t.name)}
              className={onPick ? "cursor-pointer hover:brightness-150" : undefined}>
              <title>{t.name}</title>
              <rect x="8" y={9 + i * 12.5} width="58" height="9" rx="1.5" fill={isActive ? "#20304e" : "#182236"} />
              <circle cx="14" cy={13.5 + i * 12.5} r="2.6" fill={led} className={isActive ? "fleet-led" : undefined} />
              <rect x="20" y={11.5 + i * 12.5} width={Math.min(40, t.name.length * 3.4)} height="4" rx="1" fill={label} />
            </g>
          );
        })}
      </svg>
      <span className="mt-1 font-mono text-[9px] uppercase tracking-[0.2em] text-fg-faint">tools</span>
    </div>
  );
}

export function CoffeeMachine() {
  return (
    <svg viewBox="0 0 40 52" width="100%" style={crisp} aria-hidden>
      <rect x="4" y="6" width="32" height="42" rx="2" fill="#31405e" />
      <rect x="8" y="10" width="24" height="10" fill="#0f1523" />
      <rect x="10" y="12" width="12" height="4" fill="#34d399" opacity="0.8" />
      <rect x="14" y="24" width="12" height="10" fill="#0f1523" />
      <rect x="17" y="30" width="6" height="6" fill="#b8793f" />
      <g className="fleet-steam">
        <rect x="18" y="20" width="2" height="4" fill="#9aa3b6" opacity="0.5" />
        <rect x="21" y="18" width="2" height="4" fill="#9aa3b6" opacity="0.35" />
      </g>
    </svg>
  );
}

export function Plant() {
  return (
    <svg viewBox="0 0 30 40" width="100%" style={crisp} aria-hidden>
      <rect x="6" y="2" width="6" height="14" fill="#2f9e5f" />
      <rect x="14" y="0" width="6" height="16" fill="#37b56d" />
      <rect x="20" y="4" width="5" height="12" fill="#2f9e5f" />
      <rect x="8" y="16" width="14" height="4" fill="#26824e" />
      <rect x="7" y="20" width="16" height="12" fill="#8a5a33" />
      <rect x="9" y="32" width="12" height="3" fill="#6d4526" />
    </svg>
  );
}

export function OfficeDoor() {
  return (
    <div className="flex flex-col items-center">
      <span className="mb-0.5 rounded-sm bg-fail/20 px-1.5 font-mono text-[8px] tracking-[0.25em] text-fail">EXIT</span>
      <svg viewBox="0 0 34 52" width="100%" style={crisp} aria-hidden>
        <rect x="0" y="0" width="34" height="52" fill="#3a2c1c" />
        <rect x="3" y="3" width="28" height="49" fill="#241a10" />
        <rect x="6" y="6" width="22" height="20" fill="#171009" />
        <circle cx="26" cy="30" r="2" fill="#c9a227" />
      </svg>
    </div>
  );
}
