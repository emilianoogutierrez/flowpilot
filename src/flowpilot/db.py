from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


def current_time(session: Session) -> float:
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        return float(session.scalar(text("SELECT EXTRACT(EPOCH FROM clock_timestamp())")))
    if dialect == "sqlite":
        return float(session.scalar(text("SELECT (julianday('now') - 2440587.5) * 86400.0")))
    raise RuntimeError(f"Unsupported database dialect: {dialect}")


class Database:
    def __init__(self, url: str):
        if url.startswith("sqlite"):
            path = url.removeprefix("sqlite:///")
            if path != ":memory:":
                Path(path).parent.mkdir(parents=True, exist_ok=True)
        options = {"connect_args": {"check_same_thread": False, "timeout": 30}} if url.startswith("sqlite") else {}
        self.engine: Engine = create_engine(url, pool_pre_ping=True, **options)
        if url.startswith("sqlite"):
            event.listen(self.engine, "connect", self._configure_sqlite)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)

    def close(self) -> None:
        self.engine.dispose()

    def current_time(self, session: Session) -> float:
        return current_time(session)

    @staticmethod
    def _configure_sqlite(connection, _record):
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA busy_timeout = 30000")

    @contextmanager
    def transaction(self) -> Iterator[Session]:
        with self.sessions() as session:
            try:
                # SQLite has no row locks; serialize writers before their first read.
                if self.engine.dialect.name == "sqlite":
                    session.connection().exec_driver_sql("BEGIN IMMEDIATE")
                yield session
                session.commit()
            except BaseException:
                session.rollback()
                raise
