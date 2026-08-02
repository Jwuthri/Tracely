// The three things an evaluator can be pointed at, in the order they nest. Same vocabulary the
// recording writes (`eval:<thread>:step`) and the table's own S/M/C, so there is one set of words
// for one idea.
//
// Plain module, not part of the "use client" component: a Server Component importing a value from
// a client module gets a reference proxy, not the array (`LEVELS.map is not a function`).
export type EvalLevel = "step" | "msg" | "conv";

export const LEVELS: { key: EvalLevel; label: string; hint: string }[] = [
  { key: "step", label: "Step", hint: "Every event inside a message — tool calls, thinking, agent hand-offs" },
  { key: "msg", label: "Message", hint: "One grade per message: the user's request and the answer" },
  { key: "conv", label: "Conversation", hint: "One grade for the whole thread" },
];
