from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.storage.schema import Base


class DatabaseManager:
    def __init__(self, url: str) -> None:
        if url.startswith("sqlite:///"):
            database_path = Path(url.removeprefix("sqlite:///"))
            database_path.parent.mkdir(parents=True, exist_ok=True)
        self.engine: Engine = create_engine(url, connect_args={"check_same_thread": False})
        if url.startswith("sqlite"):
            event.listen(self.engine, "connect", self._enable_sqlite_integrity)
        self._sessions = sessionmaker(bind=self.engine, expire_on_commit=False)

    @staticmethod
    def _enable_sqlite_integrity(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    def create_schema(self) -> None:
        Base.metadata.create_all(self.engine)

    def dispose(self) -> None:
        self.engine.dispose()

    @contextmanager
    def session(self) -> Iterator[Session]:
        session = self._sessions()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
