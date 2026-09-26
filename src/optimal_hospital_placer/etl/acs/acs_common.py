"""ACS 2023 five-year configuration and checksum-verified checkpoints."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
YEAR = 2023
BASE = f'https://www2.census.gov/programs-surveys/acs/summary_file/{YEAR}/table-based-SF'
TABLES = json.loads((HERE / 'tables.json').read_text(encoding='utf-8'))
RAW = ROOT / f'data/raw/ACS/{YEAR}'
PREPARED = ROOT / f'data/acs/{YEAR}'
OUTPUT = ROOT / 'data/stage4'
SHELL = f'ACS{YEAR}5YR_Table_Shells.txt'
GEOGRAPHY = f'Geos{YEAR}5YR.txt'
FILES = {SHELL: f'{BASE}/documentation/{SHELL}', GEOGRAPHY: f'{BASE}/documentation/{GEOGRAPHY}'}
FILES.update({f'acsdt5y{YEAR}-{t.lower()}.dat': f'{BASE}/data/5YRData/acsdt5y{YEAR}-{t.lower()}.dat'
              for t in TABLES})


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding='utf-8')
    temp.replace(path)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def code_hash(*names):
    return {name: sha(HERE / name) for name in ('acs_common.py', *names)}


def now():
    return datetime.now(timezone.utc).isoformat()


def reusable(directory, identity):
    manifest = directory / 'manifest.json'
    if not manifest.exists():
        return False
    data = read(manifest)
    return (data.get('status') == 'complete' and data.get('identity') == identity
            and bool(data.get('artifacts'))
            and all((directory / name).is_file() and sha(directory / name) == digest
                    for name, digest in data['artifacts'].items()))


def complete(directory, identity, names, **metadata):
    save(directory / 'manifest.json', {'status': 'complete', 'identity': identity,
         'finished_utc': now(), 'artifacts': {n: sha(directory / n) for n in names}, **metadata})


def validate_raw(name):
    path = RAW / name
    receipt = read(path.with_suffix(path.suffix + '.receipt.json'))
    if receipt.get('url') != FILES[name] or receipt.get('sha256') != sha(path):
        raise ValueError(f'ACS input checksum/URL mismatch: {path}; rerun download')
    return path, receipt['sha256']
