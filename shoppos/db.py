"""SQLite wrapper with nested transactions, sequences and migrations."""
import os
import sqlite3
from contextlib import contextmanager

from .migrations import MIGRATIONS


class Database:
    def __init__(self, path: str = ":memory:"):
        self.path = path
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        if path != ":memory:":
            self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("PRAGMA cache_size=-65536")      # 64 MB page cache
        self.conn.execute("PRAGMA mmap_size=268435456")    # memory-map up to 256 MB
        self.conn.execute("PRAGMA temp_store=MEMORY")
        self._depth = 0
        self.migrate()

    # -- schema ------------------------------------------------------------
    def migrate(self):
        current = self.conn.execute("PRAGMA user_version").fetchone()[0]
        for i in range(current, len(MIGRATIONS)):
            self.conn.execute("BEGIN")
            try:
                for stmt in _split_sql(MIGRATIONS[i]):
                    self.conn.execute(stmt)
                self.conn.execute(f"PRAGMA user_version={i + 1}")
                self.conn.execute("COMMIT")
            except Exception:
                self.conn.execute("ROLLBACK")
                raise

    @property
    def version(self) -> int:
        return self.conn.execute("PRAGMA user_version").fetchone()[0]

    # -- transactions ------------------------------------------------------
    @contextmanager
    def tx(self):
        """Atomic block. Nested use becomes a SAVEPOINT, so services compose."""
        if self._depth == 0:
            self.conn.execute("BEGIN IMMEDIATE")
            self._depth = 1
            try:
                yield self
                self.conn.execute("COMMIT")
            except BaseException:
                self.conn.execute("ROLLBACK")
                raise
            finally:
                self._depth = 0
        else:
            name = f"sp{self._depth}"
            self.conn.execute(f"SAVEPOINT {name}")
            self._depth += 1
            try:
                yield self
                self.conn.execute(f"RELEASE {name}")
            except BaseException:
                self.conn.execute(f"ROLLBACK TO {name}")
                self.conn.execute(f"RELEASE {name}")
                raise
            finally:
                self._depth -= 1

    @property
    def in_tx(self) -> bool:
        return self._depth > 0

    # -- query helpers -----------------------------------------------------
    def q(self, sql, params=()):
        return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    def one(self, sql, params=()):
        r = self.conn.execute(sql, params).fetchone()
        return dict(r) if r else None

    def scalar(self, sql, params=()):
        r = self.conn.execute(sql, params).fetchone()
        return r[0] if r else None

    def execute(self, sql, params=()):
        return self.conn.execute(sql, params)

    def insert(self, sql, params=()) -> int:
        return self.conn.execute(sql, params).lastrowid

    def many(self, sql, seq):
        self.conn.executemany(sql, seq)

    # -- sequences ---------------------------------------------------------
    def next_seq(self, name: str) -> int:
        with self.tx():
            self.conn.execute(
                "INSERT INTO sequences(name,value) VALUES(?,1) "
                "ON CONFLICT(name) DO UPDATE SET value=value+1", (name,))
            return self.scalar("SELECT value FROM sequences WHERE name=?", (name,))

    def next_number(self, name: str, prefix: str, width: int = 6) -> str:
        return f"{prefix}{self.next_seq(name):0{width}d}"

    # -- backup ------------------------------------------------------------
    def backup_to(self, dest_path: str):
        dest = sqlite3.connect(dest_path)
        try:
            self.conn.backup(dest)
        finally:
            dest.close()

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass


def _split_sql(script: str):
    """Split a script on ';' at statement ends (no ';' inside literals in our DDL)."""
    for part in script.split(";"):
        lines = [ln for ln in part.splitlines() if not ln.strip().startswith("--")]
        stmt = "\n".join(lines).strip()
        if stmt:
            yield stmt
