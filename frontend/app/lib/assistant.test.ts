import { describe, expect, it, vi, afterEach } from "vitest";
import { streamAssistantTurn, toolLabel, type AssistantEvent } from "./assistant";

// The decoder's whole job is turning a byte stream into frames, so the tests feed it bytes —
// including the case that breaks a naive `split`: one frame arriving in two chunks.
function respond(chunks: string[], ok = true, status = 200, body?: unknown) {
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const c of chunks) controller.enqueue(new TextEncoder().encode(c));
      controller.close();
    },
  });
  return {
    ok,
    status,
    statusText: "err",
    body: ok ? stream : null,
    json: async () => body,
  } as unknown as Response;
}

const frame = (o: unknown) => `data: ${JSON.stringify(o)}\n\n`;

async function collect(chunks: string[]): Promise<AssistantEvent[]> {
  const seen: AssistantEvent[] = [];
  await streamAssistantTurn(
    { message: "hi", chat_id: null, attachments: [], path: "/traces" },
    (e) => seen.push(e),
  );
  return seen;
}

afterEach(() => vi.unstubAllGlobals());

const TURN = [
  frame({ type: "tool", name: "get_trace", args: { trace_id: "t1" } }),
  frame({ type: "delta", text: "it " }),
  frame({ type: "delta", text: "failed" }),
  frame({ type: "done", chat_id: "c1", title: "why?", reply: "it failed" }),
  "data: [DONE]\n\n",
];

describe("streamAssistantTurn", () => {
  it("decodes frames in order and stops at [DONE]", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => respond([...TURN, frame({ type: "delta", text: "!" })])));
    const seen = await collect(TURN);

    expect(seen.map((e) => e.type)).toEqual(["tool", "delta", "delta", "done"]);
    expect(seen[3]).toMatchObject({ chat_id: "c1", reply: "it failed" });
  });

  it("reassembles a frame split across chunks", async () => {
    const whole = TURN.join("");
    const cut = Math.floor(whole.length / 2);
    vi.stubGlobal("fetch", vi.fn(async () => respond([whole.slice(0, cut), whole.slice(cut)])));

    expect((await collect(TURN)).map((e) => e.type)).toEqual(["tool", "delta", "delta", "done"]);
  });

  it("skips a malformed frame instead of losing the rest of the turn", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => respond(["data: {not json\n\n", ...TURN])));

    expect((await collect(TURN)).map((e) => e.type)).toEqual(["tool", "delta", "delta", "done"]);
  });

  it("rejects with the API's own detail when the stream never starts", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => respond([], false, 502, { detail: "no credit" })));

    await expect(collect([])).rejects.toThrow("no credit");
  });
});

describe("toolLabel", () => {
  it("reads the tool name back as words", () => {
    expect(toolLabel("get_trace")).toBe("get trace");
    expect(toolLabel("run_evaluation")).toBe("run evaluation");
  });
});
