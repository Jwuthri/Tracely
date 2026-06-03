"""Registry upserts (sync session, called from the Celery worker)."""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from tracely.models import Agent, AgentVersion


def upsert_agent(session: Session, project_id: str, slug: str, display_name: str = "") -> str:
    a = session.execute(
        select(Agent).where(Agent.project_id == project_id, Agent.slug == slug)
    ).scalar_one_or_none()
    if a:
        return a.id
    a = Agent(id=str(uuid4()), project_id=project_id, slug=slug, display_name=display_name or slug)
    session.add(a)
    try:
        session.commit()
    except Exception:  # concurrent insert — re-read
        session.rollback()
        a = session.execute(
            select(Agent).where(Agent.project_id == project_id, Agent.slug == slug)
        ).scalar_one()
    return a.id


def upsert_agent_version(session: Session, agent_id: str, config_hash: str, label: str = "") -> str:
    v = session.execute(
        select(AgentVersion).where(
            AgentVersion.agent_id == agent_id, AgentVersion.config_hash == config_hash
        )
    ).scalar_one_or_none()
    if v:
        return v.id
    v = AgentVersion(id=str(uuid4()), agent_id=agent_id, config_hash=config_hash, label=label)
    session.add(v)
    try:
        session.commit()
    except Exception:
        session.rollback()
        v = session.execute(
            select(AgentVersion).where(
                AgentVersion.agent_id == agent_id, AgentVersion.config_hash == config_hash
            )
        ).scalar_one()
    return v.id
