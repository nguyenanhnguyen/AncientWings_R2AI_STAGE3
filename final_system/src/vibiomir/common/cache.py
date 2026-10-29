"""Transactional, content-addressed cache shared by translation and reranking."""
import json
from pathlib import Path
import sqlite3

from .storage import sha256_text


def cache_key(value):
    return sha256_text(json.dumps(value, ensure_ascii=False, sort_keys=True))


class Cache:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), timeout=60)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, value TEXT NOT NULL)')

    def get(self, key):
        row = self.db.execute('SELECT value FROM cache WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def put_many(self, pairs):
        with self.db:
            self.db.executemany('INSERT OR REPLACE INTO cache VALUES (?, ?)',
                                [(key, json.dumps(value, ensure_ascii=False)) for key, value in pairs])

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
