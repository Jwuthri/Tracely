import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

describe("test harness", () => {
  it("renders a component", () => {
    render(<div>hello tracely</div>);
    expect(screen.getByText("hello tracely")).toBeInTheDocument();
  });
});
