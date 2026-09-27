"""Open (and if needed initialise) a database."""
from .db import Database
from .services import auth, finance, settings


def open_database(path: str = ":memory:") -> Database:
    db = Database(path)
    settings.ensure_defaults(db)
    auth.ensure_defaults(db)
    finance.ensure_defaults(db)
    return db
