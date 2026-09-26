"""Shared IO and stage 2 catalog access. No work occurs on import."""
import fnmatch
import hashlib
import json
from pathlib import Path

import pandas as pd

STATES = dict(zip(
    '01 02 04 05 06 08 09 10 11 12 13 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30 31 32 33 34 35 36 37 38 39 40 41 42 44 45 46 47 48 49 50 51 53 54 55 56'.split(),
    'AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY'.split()))
ROOT = Path(__file__).resolve().parents[4]


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str), encoding='utf-8')
    temp.replace(path)


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def text(value):
    return '' if value is None or pd.isna(value) else str(value).strip()


def save_table(frame, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False, compression='zstd')


class Catalog:
    def __init__(self, run):
        self.run = Path(run).resolve()
        self.report = read_json(self.run / 'run.json')
        if self.report.get('status') != 'complete' or self.report.get('issues') != 0:
            raise ValueError('A completed stage 2 run with zero issues is required')
        self.entries = read_json(self.run / 'tables.json')
        if len(self.entries) != self.report['tables']:
            raise ValueError('Stage 2 manifest count mismatch')
        self.inventory = read_json(self.run / 'source_inventory.json')
        self.used = {}

    def select(self, pattern):
        hits = [e for e in self.entries if fnmatch.fnmatchcase(e['input'], pattern)]
        if len(hits) != 1:
            raise ValueError(f'Expected one table matching {pattern}, found {len(hits)}')
        return hits[0]

    def load(self, entry):
        path = (self.run / entry['output']).resolve()
        if self.run not in path.parents or sha256(path) != entry['sha256']:
            raise ValueError(f'Invalid stage 2 path/checksum: {entry["input"]}')
        frame = pd.read_parquet(path)
        if len(frame) != entry['rows']:
            raise ValueError('Stage 2 row count mismatch')
        self.used[entry['input']] = entry
        return frame

    def asset(self, relative):
        hits = [a for a in self.inventory if a['relative_path'] == relative]
        if len(hits) != 1:
            raise ValueError(f'Missing inventoried raw asset: {relative}')
        item = hits[0]
        path = Path(item['path'])
        if not item.get('sha256') or sha256(path) != item['sha256']:
            raise ValueError(f'Raw asset checksum mismatch: {relative}')
        return path
