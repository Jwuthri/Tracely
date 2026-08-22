import { describe, expect, it } from "vitest";
import { closeActivity, type Activity } from "./ActivityLog";

const run = (name: string, at = 0): Activity => ({ name, at, state: "run" });

describe("closeActivity", () => {
  it("closes the most recent running call of that name, not an earlier one", () => {
    const list = [{ ...run("get_trace"), state: "ok" as const }, run("get_trace", 1)];
    expect(closeActivity(list, "get_trace", false).map((a) => a.state)).toEqual(["ok", "fail"]);
  });

  it("ignores a done frame for a tool that is not running", () => {
    const list = [run("get_trace")];
    expect(closeActivity(list, "list_clusters", true)).toBe(list);
  });
});
