"""Seed the default project + a dev ingest key."""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select

from tracely.db import SyncSessionLocal
from tracely.models import IngestKey, Project

DEFAULT_PROJECT_SLUG = "default"
DEFAULT_KEY = "tracely_dev_key"


def main() -> None:
    with SyncSessionLocal() as s:
        project = s.execute(
            select(Project).where(Project.slug == DEFAULT_PROJECT_SLUG)
        ).scalar_one_or_none()
        if not project:
            project = Project(id=str(uuid4()), slug=DEFAULT_PROJECT_SLUG, name="Default")
            s.add(project)
            s.commit()

        key = s.execute(select(IngestKey).where(IngestKey.key == DEFAULT_KEY)).scalar_one_or_none()
        if not key:
            s.add(IngestKey(id=str(uuid4()), project_id=project.id, key=DEFAULT_KEY))
            s.commit()

        print(f"project_id={project.id}  slug={project.slug}  ingest_key={DEFAULT_KEY}")


if __name__ == "__main__":
    main()
