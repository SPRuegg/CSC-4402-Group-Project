import sqlite3
from contextlib import contextmanager
from pathlib import Path

from flask import current_app, g


def get_db():
    if "db" not in g:
        database_path = current_app.config["DATABASE"]
        if database_path != ":memory:":
            Path(database_path).parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(database_path)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
        except Exception:
            connection.close()
            raise
        g.db = connection
    return g.db


def close_db(error=None):
    connection = g.pop("db", None)
    if connection is not None:
        connection.close()


@contextmanager
def transaction():
    connection = get_db()
    if connection.in_transaction:
        raise RuntimeError("A database transaction is already active")
    try:
        connection.execute("BEGIN IMMEDIATE")
        yield connection
        connection.commit()
    except BaseException:
        connection.rollback()
        raise


def init_app(app):
    app.teardown_appcontext(close_db)
