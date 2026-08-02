"""Keep the SDK test suite off any running Tracely.

`init()` takes the endpoint as a plain default — `http://localhost:8000`, the developer's own
stack — so `pytest sdk/tests` pushed a few hundred spans into whatever workspace was running, once
per run. `OTEL_SDK_DISABLED` is OpenTelemetry's own kill switch: the SDK becomes a no-op, so there
is no exporter and no background flush thread to race with teardown.

Assigned, not `setdefault`: a dev shell that exports it as "false" is exactly this case.
"""

from __future__ import annotations

import os

os.environ["OTEL_SDK_DISABLED"] = "true"
