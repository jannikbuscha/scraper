"""Request dependencies: the application context and one database session per request."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from mdt.config import Settings


@dataclass(frozen=True)
class AppContext:
    """What the handlers need from the application (``app.state.mdt``)."""

    settings: Settings
    engine: Engine
    session_factory: sessionmaker[Session]


def app_context(request: Request) -> AppContext:
    """The context of the application serving ``request``."""
    context = request.app.state.mdt
    assert isinstance(context, AppContext)
    return context


def get_session(request: Request) -> Iterator[Session]:
    """A session for one request. The domain functions run their own read and write
    units; whatever is still open at the end is committed on success and rolled back on
    error, and the session is always closed."""
    session = app_context(request).session_factory()
    try:
        yield session
    except BaseException:
        session.rollback()
        raise
    else:
        if session.in_transaction():
            session.commit()
    finally:
        session.close()


async def settings_of(request: Request) -> Settings:
    """The application settings."""
    return app_context(request).settings


#: The request's session; it is closed when the handler returns (before the response is
#: sent), so streamed exports use a session of their own.
SessionDep = Annotated[Session, Depends(get_session, scope="function")]
SettingsDep = Annotated[Settings, Depends(settings_of)]
