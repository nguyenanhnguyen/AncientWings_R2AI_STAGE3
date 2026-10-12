"""Disk-backed passage text; metadata stays in RAM, only candidate text is fetched.

The sidecar is derived from the chunk Parquet, never an independent source of truth.
"""
from collections import OrderedDict
from contextlib import closing
from pathlib import Path
import sqlite3

import pyarrow.parquet as pq

from ..corpus.chunk import retrieval_text


class PassageStore:
    def __init__(self, chunks_path, cache_path, fingerprint, capacity=8192):
        self.path = Path(cache_path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        valid = False
        if self.path.exists():
            with closing(sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True)) as db:
                valid = db.execute('SELECT digest FROM meta').fetchone() == (fingerprint,)
        if not valid:
            temporary = self.path.with_suffix('.building.sqlite')
            temporary.unlink(missing_ok=True)
            with closing(sqlite3.connect(temporary)) as db:
                db.execute('CREATE TABLE passages (rowid INTEGER PRIMARY KEY, title TEXT, text TEXT)')
                db.execute('CREATE TABLE meta (digest TEXT)')
                row = 0
                for batch in pq.ParquetFile(chunks_path).iter_batches(batch_size=4096, columns=['title', 'text']):
                    records = batch.to_pylist()
                    with db:
                        db.executemany('INSERT INTO passages VALUES (?, ?, ?)',
                                       [(row + i, r['title'], r['text']) for i, r in enumerate(records)])
                    row += len(records)
                with db:
                    db.execute('INSERT INTO meta VALUES (?)', (fingerprint,))
            temporary.replace(self.path)
        self.db = sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True)
        self.cache, self.capacity = OrderedDict(), capacity

    def __getitem__(self, row):
        row = int(row)
        if row not in self.cache:
            value = self.db.execute('SELECT title, text FROM passages WHERE rowid=?', (row,)).fetchone()
            if value is None:
                raise IndexError(row)
            self.cache[row] = retrieval_text({'title': value[0], 'text': value[1]})
            if len(self.cache) > self.capacity:
                self.cache.popitem(last=False)
        self.cache.move_to_end(row)
        return self.cache[row]

    def close(self):
        self.db.close()


def main():
    import argparse
    from ..common.storage import sha256_file
    parser = argparse.ArgumentParser(description='Build the read-only passage store before GPU query shards.')
    parser.add_argument('--chunks', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    store = PassageStore(args.chunks, args.out, sha256_file(args.chunks))
    store.close()
