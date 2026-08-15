import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";

vi.mock("@/app/lib/evaluators", async (orig) => ({
  ...(await orig<Record<string, unknown>>()),
  listEvaluators: vi.fn(async () => []),
  listTemplates: vi.fn(async () => []),
  listJudgeModels: vi.fn(async () => ({ models: [], default: "" })),
}));

import { AddColumnModal } from "@/app/components/AddColumnModal";

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 200 })));
});

function open(onClose: () => void) {
  render(<AddColumnModal open onClose={onClose} onSaved={vi.fn()} />);
}

describe("AddColumnModal close guard", () => {
  it("closes on Esc while untouched, and never on a backdrop click", () => {
    const onClose = vi.fn();
    open(onClose);
    fireEvent.click(screen.getByRole("dialog"));
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("asks before discarding a half-written column", () => {
    const onClose = vi.fn();
    open(onClose);
    fireEvent.click(screen.getByText("Manual"));
    fireEvent.change(screen.getByPlaceholderText("e.g., Helpfulness Score"), {
      target: { value: "Helpfulness" },
    });

    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    fireEvent.click(screen.getByLabelText("Close"));
    expect(confirm).toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();

    confirm.mockReturnValue(true);
    fireEvent.click(screen.getByLabelText("Close"));
    expect(onClose).toHaveBeenCalledTimes(1);
    confirm.mockRestore();
  });
});
