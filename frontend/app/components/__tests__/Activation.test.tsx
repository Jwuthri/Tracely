import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Activation, type ActivationState } from "../Activation";

const state = (over: Partial<ActivationState> = {}): ActivationState => ({
  traces: 0, evaluators: 0, failures: 0, clusters: 0, cases: 0, gates: 0,
  ingestKey: "tracely_k_abc", endpoint: "https://api.example.com",
  ...over,
});

describe("Activation", () => {
  it("opens a brand-new workspace on step 1, with a runnable snippet", () => {
    render(<Activation {...state()} />);
    expect(screen.getByText("0 / 5")).toBeTruthy();
    // the first step is the expanded one and its snippet carries THIS workspace's key + host
    const code = screen.getByText(/tracely.init/).textContent ?? "";
    expect(code).toContain('api_key="tracely_k_abc"');
    expect(code).toContain('endpoint="https://api.example.com"');
    // later steps are collapsed — no second snippet on screen
    expect(screen.queryByText(/tracely replay/)).toBeNull();
  });

  it("expands the first UNFINISHED step and shows proof for the finished ones", () => {
    render(<Activation {...state({ traces: 1204, evaluators: 3 })} />);
    expect(screen.getByText("2 / 5")).toBeTruthy();
    expect(screen.getByText("1,204 traces")).toBeTruthy();
    expect(screen.getByText("3 evaluators")).toBeTruthy();
    expect(screen.getByText(/Nothing to do here/)).toBeTruthy();   // step 3 is current
    expect(screen.queryByText(/tracely.init/)).toBeNull();          // step 1 collapsed again
  });

  it("counts a cluster as a caught failure", () => {
    // clusters come from raw execution errors too, with no evaluator scoring anything FAIL —
    // the step must not read "not done" next to a full clusters page
    render(<Activation {...state({ traces: 66, evaluators: 6, clusters: 5 })} />);
    expect(screen.getByText("5 clustered")).toBeTruthy();
    expect(screen.getByText("3 / 5")).toBeTruthy();
  });

  it("disappears once the loop has been closed once", () => {
    const { container } = render(
      <Activation {...state({ traces: 9, evaluators: 1, failures: 4, cases: 1, gates: 1 })} />,
    );
    expect(container.firstChild).toBeNull();
  });
});
