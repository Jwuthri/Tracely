/** What a reviewer should DO with an agreement number.
 *
 * The page's whole point is deciding whether to let a judge block a merge, and a bare "0%" doesn't
 * say which way it is wrong or what to do about it. The two error directions are not symmetric:
 * missed failures make the gate useless, over-flags make it hostile. */

export type Calibration = {
  labeled: number;
  agreement: number;
  false_pass: number; // judge PASS, human FAIL — a failure the gate would wave through
  false_fail: number; // judge FAIL, human PASS — a good run the gate would block
};

export type Takeaway = { tone: "ok" | "warn" | "fail"; text: string };

/** null until there are enough labels to say anything honest. */
export function judgeTakeaway(c: Calibration, min = 3): Takeaway | null {
  if (c.labeled < min) return null;
  const wrong = c.false_pass + c.false_fail;
  if (wrong === 0)
    return {
      tone: "ok",
      text: `Matches you on all ${c.labeled} runs you checked — safe to let it block a merge.`,
    };
  if (c.false_pass >= c.false_fail)
    return {
      tone: "fail",
      text: `Misses failures: ${c.false_pass} of ${c.labeled} runs you failed, this judge passed. As a gate it would wave those through — tighten the rubric before you trust it.`,
    };
  return {
    tone: "warn",
    text: `Over-flags: ${c.false_fail} of ${c.labeled} runs you passed, this judge failed. As a gate it would block good PRs — loosen the rubric, or keep it advisory until it settles.`,
  };
}
