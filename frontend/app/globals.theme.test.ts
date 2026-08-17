import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

/* The two palettes are two hand-written blocks in globals.css. A token defined in one and not
   the other does not error — it silently INHERITS the other theme's value, which is how you get
   white-on-white. Assert they stay in lockstep. */

const css = readFileSync(join(__dirname, "globals.css"), "utf8");
const block = (selector: string) => {
  const start = css.indexOf(selector);
  expect(start, `${selector} block missing from globals.css`).toBeGreaterThan(-1);
  return css.slice(start, css.indexOf("\n}", start));
};
const tokens = (selector: string) =>
  new Set([...block(selector).matchAll(/^\s*(--[\w-]+):/gm)].map((m) => m[1]));

describe("theme palettes", () => {
  const dark = tokens(':root,\n[data-theme="dark"] {');
  const light = tokens('[data-theme="light"] {');

  it("defines a light value for every dark token", () => {
    expect([...dark].filter((t) => !light.has(t))).toEqual([]);
  });

  it("defines no light token the dark theme lacks", () => {
    expect([...light].filter((t) => !dark.has(t))).toEqual([]);
  });

  it("keeps the dark palette re-appliable to a nested subtree", () => {
    // the marketing page and the Fleet office pin themselves dark inside a light app
    expect(css).toContain(':root,\n[data-theme="dark"] {');
  });

  it("declares a color-scheme per theme so native controls follow", () => {
    expect(block(':root,\n[data-theme="dark"] {')).toContain("color-scheme: dark");
    expect(block('[data-theme="light"] {')).toContain("color-scheme: light");
  });
});
