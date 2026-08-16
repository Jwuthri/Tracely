import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MessageContent, StateCell, TurnMessage, stateWritesOf } from "./content";
import { classifyBlock } from "./content";
import type { SpanOut } from "../../lib/api";

/* The payloads here are the real wire shapes, not invented ones: three providers describe an
   image three ways, an assistant turn that only calls tools carries empty content, and a tool
   result arrives as a JSON string. Every one of them has produced a rendering bug at some point. */

describe("classifyBlock — one concept, three provider spellings", () => {
  it("reads an Anthropic base64 image block", () => {
    const part = classifyBlock({
      type: "image",
      source: { type: "base64", media_type: "image/png", data: "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk" },
    });
    expect(part.kind).toBe("image");
  });

  it("reads an OpenAI image_url block", () => {
    expect(classifyBlock({ type: "image_url", image_url: { url: "https://x/y.png" } }).kind).toBe("image");
  });

  it("reads plain text, a bare string, and a document", () => {
    expect(classifyBlock({ type: "text", text: "hello" })).toEqual({ kind: "text", text: "hello" });
    expect(classifyBlock("hello")).toEqual({ kind: "text", text: "hello" });
    expect(classifyBlock({ type: "document", filename: "invoice.pdf" }).kind).toBe("file");
  });

  it("shows the raw block when an image has no src we can render", () => {
    // a mute "image" chip here HIDES what actually arrived — the JSON is the honest fallback
    expect(classifyBlock({ type: "image", source: {} }).kind).toBe("json");
  });

  it("falls back to JSON for a shape it does not know", () => {
    expect(classifyBlock({ type: "audio", data: "…" }).kind).toBe("json");
  });
});

describe("MessageContent", () => {
  it("renders a chat transcript as a conversation, not as JSON", () => {
    render(<MessageContent raw={JSON.stringify([
      { role: "user", content: "where is my order?" },
      { role: "assistant", content: "let me check" },
    ])} />);
    // collapsed, the pill teases the LAST conversational turn — the transcript is in the popover
    expect(screen.getByText(/let me check/)).toBeTruthy();
    expect(screen.queryByText(/"role"/)).toBeNull();  // never the raw envelope
  });

  it("keeps a tool-calling assistant turn visible when its content is empty", () => {
    // the exact shape that rendered as blank: content "" with the work in tool_calls
    render(<MessageContent raw={JSON.stringify({
      role: "assistant",
      content: "",
      tool_calls: [{ id: "c1", type: "function", function: { name: "lookup_order", arguments: '{"id":"4471"}' } }],
    })} />);
    expect(screen.getByText(/lookup_order/)).toBeTruthy();
  });

  it("unwraps a promptish kwarg but leaves tool args as data", () => {
    render(<MessageContent raw={JSON.stringify({ question: "how long is the warranty?" })} />);
    expect(screen.getByText(/how long is the warranty/)).toBeTruthy();

    const { container } = render(<MessageContent raw={JSON.stringify({ order_id: "ORD-4471" })} />);
    expect(container.textContent).toContain("order_id"); // structured data stays structured
  });

  it("renders a {messages:[…]} wrapper as the conversation inside it", () => {
    render(<MessageContent raw={JSON.stringify({ messages: [{ role: "user", content: "hi from langgraph" }] })} />);
    expect(screen.getByText(/hi from langgraph/)).toBeTruthy();
  });

  it("passes plain text through and shows a dash for nothing", () => {
    render(<MessageContent raw="just a sentence" />);
    expect(screen.getByText("just a sentence")).toBeTruthy();
    const { container } = render(<MessageContent raw={null} />);
    expect(container.textContent).toBe("—");
    const broken = render(<MessageContent raw="{not json" />);
    expect(broken.container.textContent).toContain("{not json"); // never blank on malformed JSON
  });
});

describe("TurnMessage", () => {
  const convo = JSON.stringify([
    { role: "user", content: "first question" },
    { role: "assistant", content: "first answer" },
    { role: "user", content: "second question" },
  ]);

  it("shows the LAST message of the asked-for role", () => {
    render(<TurnMessage raw={convo} role="user" />);
    expect(screen.getByText(/second question/)).toBeTruthy();
    expect(screen.queryByText(/first question/)).toBeNull();
  });

  it("shows a dash when that role never spoke", () => {
    const { container } = render(
      <TurnMessage raw={JSON.stringify([{ role: "user", content: "only me" }])} role="assistant" />,
    );
    expect(container.textContent).toBe("—");
  });
});

describe("state writes", () => {
  const span = (writes: Record<string, unknown>) =>
    ({
      metadata: Object.fromEntries(
        Object.entries(writes).map(([k, v]) => [`tracely.state.${k}`, JSON.stringify(v)]),
      ),
    }) as unknown as SpanOut;

  it("merges a turn's writes with later spans winning", () => {
    expect(stateWritesOf([span({ plan: ["a"], step: 1 }), span({ step: 2 })])).toEqual({
      plan: ["a"],
      step: 2,
    });
  });

  it("is null when nothing was written", () => {
    expect(stateWritesOf([])).toBeNull();
    const { container } = render(<StateCell writes={null} />);
    expect(container.textContent).toBe("—");
  });
});
