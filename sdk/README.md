# tracely-sdk

Thin Python SDK to instrument an agent and export traces to Tracely over OTLP.
It's a small wrapper over the OpenTelemetry SDK that sets standard `gen_ai.*` attributes
plus Tracely's first-class `tracely.*` hints (agent / version / run / conversation / turn / step / env).

```python
import tracely_sdk as tracely

tracely.init(endpoint="http://localhost:8000", api_key="tracely_dev_key", service_name="my-agent")

with tracely.agent("planner", version="v1") as a:           # AGENT span (becomes the run root)
    with tracely.turn("t1", index=0):                       # multi-turn grouping
        with tracely.llm("gpt-4o") as g:                    # GENERATION span
            tracely.set_io(g, input=prompt, output=completion)
            tracely.set_usage(g, input_tokens=812, output_tokens=96)
        with tracely.tool("get_weather") as t:              # TOOL span
            try:
                ...
            except Exception as e:
                tracely.error(t, str(e))                    # level=ERROR -> failure signal

tracely.flush()
```

Already using OpenTelemetry / OpenInference / LangGraph instrumentation? You don't need this SDK —
point your existing OTLP exporter at `POST {endpoint}/v1/traces` with
`Authorization: Bearer <ingest-key>`. This SDK is just the ergonomic path.

Try it (with the stack running): `uv run python sdk/example.py`
