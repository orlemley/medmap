"""Inventory sources and ZIP members without extracting or interpreting geometry."""
import json
from pathlib import Path
from zipfile import ZipFile

from common import SOURCES, sha256


def inventory(raw: Path, selected: list[str]) -> tuple[list[dict], list[dict]]:
    assets, issues = [], []
    for source in selected:
        folder = raw / source
        if not folder.is_dir():
            issues.append({'source': source, 'error': 'Source directory is missing'})
            continue
        paths = [p for p in sorted(folder.rglob('*')) if p.is_file()
                 and not p.name.endswith(('.receipt.json', '.part'))]
        if not paths:
            issues.append({'source': source, 'error': 'Source directory has no inputs'})
        for path in paths:
            if path.is_symlink():
                issues.append({'source': source, 'path': str(path), 'error': 'Symlink input is not supported'})
                continue
            asset = {'source': source, 'path': str(path), 'relative_path': path.relative_to(raw).as_posix(),
                     'bytes': path.stat().st_size, 'mtime_ns': path.stat().st_mtime_ns,
                     'sha256': None, 'receipt': None, 'members': [], 'status': 'ready'}
            try:
                receipt_path = Path(str(path) + '.receipt.json')
                if receipt_path.exists():
                    asset['receipt'] = json.loads(receipt_path.read_text(encoding='utf-8-sig'))
                # The road extract can be many GB. Inventory it, but do not read it
                # or claim that the downloader's recorded hash was reverified.
                if path.name.endswith('.osm.pbf'):
                    asset['hash_status'] = 'deferred_road_file'
                else:
                    asset['sha256'] = sha256(path)
                    asset['hash_status'] = 'computed'
                    expected = (asset['receipt'] or {}).get('Sha256')
                    if expected and expected.lower() != asset['sha256']:
                        raise ValueError('Input checksum differs from downloader receipt')
                if path.suffix.lower() == '.zip':
                    with ZipFile(path) as archive:
                        asset['members'] = [{'name': member.filename, 'bytes': member.file_size}
                                            for member in archive.infolist() if not member.is_dir()]
            except Exception as exc:
                asset['status'] = 'failed'
                issues.append({'source': source, 'path': str(path), 'error': str(exc)})
            assets.append(asset)
    return assets, issues
