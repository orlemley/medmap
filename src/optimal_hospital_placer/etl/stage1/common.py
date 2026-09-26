"""Small filesystem helpers; importing this module performs no work."""
import hashlib
import json
import re
from pathlib import Path

SOURCES = ('ACS', 'AHRF', 'CMSFacilities', 'CMSHospital', 'HPSA', 'MUAP',
           'PLACES', 'RUCA', 'SVI', 'OSM')


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding='utf-8')
    temporary.replace(path)


def normalize_headers(headers: list[str]) -> list[str]:
    """Normalize only headers. Resolve collisions without losing any columns."""
    used = set()
    names = []
    for index, header in enumerate(headers, 1):
        base = re.sub(r'[^a-z0-9]+', '_', header.strip().lower()).strip('_')
        base = base or f'column_{index}'
        name = base
        suffix = 2
        while name in used:
            name = f'{base}__{suffix}'
            suffix += 1
        used.add(name)
        names.append(name)
    return names
