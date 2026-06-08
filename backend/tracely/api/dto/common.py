"""Cross-cutting response models used by more than one router."""

from __future__ import annotations

from pydantic import BaseModel


class IngestResponse(BaseModel):
    batch_id: str
    accepted: bool = True


class AgentOut(BaseModel):
    id: str
    slug: str
    display_name: str
    kind: str
    role: str
