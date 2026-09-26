"""Download 2023 Census TIGER/Line ZIPs only when explicitly executed."""
import argparse
import time
import urllib.request
from pathlib import Path
from zipfile import ZipFile

from s3_common import ROOT, STATES, read_json, save_json, sha256


def prepare(directory, states):
    directory.mkdir(parents=True, exist_ok=True)
    files = [('COUNTY', 'tl_2023_us_county.zip')]
    files += [('TRACT', f'tl_2023_{state}_tract.zip') for state in states]
    records = []
    for folder, name in files:
        path = directory / name
        url = f'https://www2.census.gov/geo/tiger/TIGER2023/{folder}/{name}'
        receipt = directory / f'{name}.receipt.json'
        if path.exists() and receipt.exists():
            old = read_json(receipt)
            if old['url'] == url and old['sha256'] == sha256(path):
                records.append(old)
                continue
        temp = directory / f'{name}.part'
        for attempt in range(3):
            try:
                print(f'Downloading {name}', flush=True)
                request = urllib.request.Request(url, headers={'User-Agent': 'HospitalInfrastructureETL/1.0'})
                with urllib.request.urlopen(request, timeout=180) as response, temp.open('wb') as output:
                    while chunk := response.read(1024 * 1024):
                        output.write(chunk)
                with ZipFile(temp) as archive:
                    if archive.testzip() is not None or not any(n.endswith('.shp') for n in archive.namelist()):
                        raise ValueError('Invalid boundary ZIP')
                temp.replace(path)
                record = {'url': url, 'file': name, 'sha256': sha256(path), 'vintage': 2023}
                save_json(receipt, record)
                records.append(record)
                break
            except Exception:
                temp.unlink(missing_ok=True)
                if attempt == 2:
                    raise
                time.sleep(2 ** (attempt + 1))
    save_json(directory / 'manifest.json', records)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, default=ROOT / 'data/reference/tiger2023')
    parser.add_argument('--states', nargs='+', choices=list(STATES), default=list(STATES))
    args = parser.parse_args()
    prepare(args.directory.resolve(), list(dict.fromkeys(args.states)))
