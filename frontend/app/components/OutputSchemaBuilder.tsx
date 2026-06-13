"use client";

import { useEffect, useRef, useState, type SVGProps } from "react";

// ── Output Schema builder (the JSON Object output type) ────────────────────────
// TurnWise-style row editor: each row is one property of the evaluation output. Nothing is
// appended by the platform — the column returns exactly these fields. To make the column drive
// PASS/FAIL and gates, the user adds a numeric `score` (0–1) field; a `reason` string carries
// the explanation. `enum` is a pseudo-type that compiles to `type: "string"` + `enum: [...]` —
// and unlike TurnWise, the backend enforces it at grading time (Literal constraint). Emits a
// flat JSON Schema on every change.

const svg = (p: SVGProps<SVGSVGElement>) => ({
  xmlns: "http://www.w3.org/2000/svg",
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 2,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  ...p,
});
const TrashIcon = (p: SVGProps<SVGSVGElement>) => (
  <svg {...svg(p)}><path d="M3 6h18" /><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" /><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" /></svg>
);
const PlusIcon = (p: SVGProps<SVGSVGElement>) => (
  <svg {...svg(p)}><path d="M5 12h14" /><path d="M12 5v14" /></svg>
);

export type SchemaFieldRow = {
  id: string;
  name: string;
  type: "string" | "number" | "boolean" | "array" | "object" | "enum";
  description: string;
  required: boolean;
  enumValues: string; // comma-separated
  // The original property spec (from templates / AI / API-created schemas). Carries what the
  // row UI doesn't edit — array `items` (incl. item enums), nested object `properties` — so a
  // no-edit save round-trips losslessly instead of degrading typed arrays to bare ones.
  raw?: Record<string, unknown>;
};

const FIELD_TYPES: { value: SchemaFieldRow["type"]; label: string }[] = [
  { value: "string", label: "String" },
  { value: "number", label: "Number" },
  { value: "boolean", label: "Boolean" },
  { value: "enum", label: "Enum" },
  { value: "array", label: "Array" },
  { value: "object", label: "Object" },
];

// Nothing is added implicitly — the builder starts with the fields a typical metric wants
// (a 0–1 `score` and a `reason`), fully editable and removable, so the user defines exactly the
// output shape.
const DEFAULT_ROWS: SchemaFieldRow[] = [
  { id: "1", name: "score", type: "number", description: "0–1 score — drives PASS/FAIL and gates", required: true, enumValues: "" },
  { id: "2", name: "reason", type: "string", description: "Why this score", required: true, enumValues: "" },
];

export function buildJsonSchema(rows: SchemaFieldRow[]): Record<string, unknown> {
  const properties: Record<string, unknown> = {};
  const required: string[] = [];
  for (const row of rows) {
    const name = row.name.trim();
    if (!name) continue;
    const prop: Record<string, unknown> = {};
    if (row.type === "enum") {
      prop.type = "string";
      const values = row.enumValues.split(",").map((v) => v.trim()).filter(Boolean);
      if (values.length > 0) prop.enum = values;
    } else {
      prop.type = row.type;
      // carry through the parts the UI doesn't edit, but only while the type still matches
      // (switching array → string must not smuggle stale `items` along)
      if (row.raw && row.raw.type === row.type) {
        if (row.type === "array" && row.raw.items != null) prop.items = row.raw.items;
        if (row.type === "object") {
          if (row.raw.properties != null) prop.properties = row.raw.properties;
          if (row.raw.required != null) prop.required = row.raw.required;
        }
      }
    }
    if (row.description.trim()) prop.description = row.description.trim();
    properties[name] = prop;
    if (row.required) required.push(name);
  }
  return { type: "object", properties, required };
}

export function rowsFromJsonSchema(schema: Record<string, unknown> | undefined): SchemaFieldRow[] | null {
  if (!schema || typeof schema !== "object" || !("properties" in schema)) return null;
  const properties = (schema.properties ?? {}) as Record<string, Record<string, unknown>>;
  const required = new Set((schema.required as string[]) ?? []);
  const rows = Object.entries(properties).map(([name, prop], i) => {
    const isEnum = Array.isArray(prop.enum) && prop.enum.length > 0;
    return {
      id: String(i + 1),
      name,
      type: (isEnum ? "enum" : (prop.type as SchemaFieldRow["type"]) || "string") as SchemaFieldRow["type"],
      description: String(prop.description ?? ""),
      required: required.has(name),
      enumValues: isEnum ? (prop.enum as unknown[]).join(", ") : "",
      raw: prop,
    };
  });
  return rows.length > 0 ? rows : null;
}

const INPUT =
  "rounded-lg border border-line bg-ink-900/80 px-2.5 py-1.5 text-[12px] text-fg placeholder:text-fg-faint/60 focus:border-signal/40 focus:outline-none";

export function OutputSchemaBuilder({
  schema,
  onChange,
}: {
  schema: Record<string, unknown> | undefined;
  onChange: (schema: Record<string, unknown>) => void;
}) {
  const [rows, setRows] = useState<SchemaFieldRow[]>(() => rowsFromJsonSchema(schema) ?? DEFAULT_ROWS);
  const nextId = useRef(100);

  // Emit the initial (default or hydrated) schema once so a no-edit Create still carries it.
  const emittedInitial = useRef(false);
  useEffect(() => {
    if (!emittedInitial.current) {
      emittedInitial.current = true;
      onChange(buildJsonSchema(rows));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function update(updated: SchemaFieldRow[]) {
    setRows(updated);
    onChange(buildJsonSchema(updated));
  }

  function patchRow(id: string, patch: Partial<SchemaFieldRow>) {
    update(rows.map((r) => (r.id === id ? { ...r, ...patch } : r)));
  }

  return (
    <div className="space-y-4">
      <div>
        <h3 className="text-[13px] font-medium text-fg">Output fields</h3>
        <p className="text-[11.5px] text-fg-faint">
          Define exactly the fields this metric returns — nothing is added automatically. Include a
          numeric <span className="font-mono text-fg-muted">score</span> (0–1) to drive PASS/FAIL
          and gates, and a <span className="font-mono text-fg-muted">reason</span> for the
          explanation. Enum fields are strictly enforced — the judge cannot return a label outside
          the list.
        </p>
      </div>

      <div className="space-y-2">
        {rows.map((row) => (
          <div key={row.id} className="space-y-2 rounded-lg border border-line bg-ink-700/50 p-3">
            <div className="flex items-center gap-2">
              <input
                value={row.name}
                onChange={(e) => patchRow(row.id, { name: e.target.value })}
                placeholder="Field name"
                className={`${INPUT} min-w-0 flex-1 font-mono`}
              />
              <select
                value={row.type}
                onChange={(e) => patchRow(row.id, { type: e.target.value as SchemaFieldRow["type"] })}
                className={`${INPUT} w-28 shrink-0`}
              >
                {FIELD_TYPES.map((t) => (
                  <option key={t.value} value={t.value}>{t.label}</option>
                ))}
              </select>
              <label className="flex shrink-0 cursor-pointer items-center gap-1.5 text-[11px] text-fg-muted">
                <input
                  type="checkbox"
                  checked={row.required}
                  onChange={(e) => patchRow(row.id, { required: e.target.checked })}
                  className="accent-blue-500"
                />
                Req
              </label>
              <button
                onClick={() => update(rows.filter((r) => r.id !== row.id))}
                className="shrink-0 rounded-md p-1.5 text-fg-faint transition-colors hover:bg-fail/10 hover:text-fail"
                title="Remove field"
              >
                <TrashIcon className="h-3.5 w-3.5" />
              </button>
            </div>
            {row.type === "enum" && (
              <input
                value={row.enumValues}
                onChange={(e) => patchRow(row.id, { enumValues: e.target.value })}
                placeholder="Comma-separated values (e.g., none, mild, moderate, severe)"
                className={`${INPUT} w-full font-mono`}
              />
            )}
            <input
              value={row.description}
              onChange={(e) => patchRow(row.id, { description: e.target.value })}
              placeholder="Description (optional)"
              className={`${INPUT} w-full`}
            />
          </div>
        ))}
      </div>

      <button
        onClick={() => update([...rows, {
          id: String(nextId.current++), name: "", type: "string", description: "", required: false, enumValues: "",
        }])}
        className="flex w-full items-center justify-center gap-1.5 rounded-lg border border-dashed border-line px-3 py-2 text-[12.5px] text-fg-muted transition-colors hover:border-line-bright hover:text-fg"
      >
        <PlusIcon className="h-3.5 w-3.5" />
        Add Field
      </button>

      <div>
        <div className="mb-1.5 text-[10px] font-medium uppercase tracking-wider text-fg-faint">Schema preview</div>
        <pre className="max-h-56 overflow-auto rounded-lg border border-line bg-ink/60 p-3 font-mono text-[11px] leading-relaxed text-fg-muted">
          {JSON.stringify(buildJsonSchema(rows), null, 2)}
        </pre>
      </div>
    </div>
  );
}
