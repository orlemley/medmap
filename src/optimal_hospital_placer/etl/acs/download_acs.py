"""Download selected public ACS summary files; no Census API or key."""
import time

import requests

from acs_common import FILES, RAW, now, read, save, sha


def download():
    RAW.mkdir(parents=True, exist_ok=True)
    for name, url in FILES.items():
        path = RAW / name
        receipt = path.with_suffix(path.suffix + '.receipt.json')
        if path.exists() and receipt.exists():
            info = read(receipt)
            if info.get('url') == url and info.get('sha256') == sha(path):
                print(f'Using cached {name}', flush=True)
                continue
        temporary = path.with_suffix(path.suffix + '.part')
        for attempt in range(1, 6):
            try:
                print(f'Downloading {name}, attempt {attempt}/5', flush=True)
                with requests.get(url, stream=True, timeout=(30, 180),
                                  headers={'Accept-Encoding': 'identity'}) as response:
                    response.raise_for_status()
                    if 'text/html' in response.headers.get('Content-Type', '').lower():
                        raise ValueError(f'Unexpected HTML instead of ACS data: {url}')
                    with temporary.open('wb') as stream:
                        for chunk in response.iter_content(1024 * 1024):
                            stream.write(chunk)
                    size = temporary.stat().st_size
                    expected = response.headers.get('Content-Length')
                    if size == 0 or (expected and size != int(expected)):
                        raise requests.ConnectionError('Incomplete download')
                with temporary.open('r', encoding='utf-8-sig') as stream:
                    header = stream.readline()
                required = 'Table ID|' if 'Shells' in name else ('FILEID|' if name.startswith('Geos') else 'GEO_ID|')
                if not header.startswith(required):
                    raise ValueError(f'Unexpected ACS header in {name}')
                digest = sha(temporary)
                temporary.replace(path)
                save(receipt, {'url': url, 'sha256': digest, 'bytes': size, 'fetched_utc': now()})
                break
            except (requests.Timeout, requests.ConnectionError, requests.HTTPError) as exc:
                if isinstance(exc, requests.HTTPError) and exc.response.status_code not in {408, 429, 500, 502, 503, 504}:
                    raise
                if attempt == 5:
                    raise
                delay = 15 * 2 ** (attempt - 1)
                print(f'{name}: {exc}; retrying in {delay}s', flush=True)
                time.sleep(delay)


if __name__ == '__main__':
    download()
