"""Single busy-wait setting for every connection to a shared SQLite file.

Without this, a caller that forgets an explicit timeout silently falls back
to Python's 5-second sqlite3 default, so the same lock contention produces a
fast failure in one module and a 30-second stall in another, making the two
impossible to correlate from symptoms alone.
"""
import sqlite3

BUSY_TIMEOUT_SECONDS = 30


def connect(database, *, timeout=BUSY_TIMEOUT_SECONDS, **kwargs):
    return sqlite3.connect(database, timeout=timeout, **kwargs)
