"""Shared SQLAlchemy declarative Base. Pulled into its own module so models can import
the metadata registry without dragging in the engine/sessionmaker (which need settings)."""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
