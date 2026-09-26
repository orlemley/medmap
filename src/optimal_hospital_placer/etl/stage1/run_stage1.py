"""Run source inventory, CSV conversion, and publication reporting (Python 3.10+)."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from common import SOURCES, write_json
from inventory import inventory


def main() -> int:
    root = Path(__file__).resolve().parents[4]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw-dir', type=Path, default=root / 'data/raw')
    parser.add_argument('--output-dir', type=Path, default=root / 'data/stage1')
    parser.add_argument('--sources', nargs='+', choices=SOURCES, default=list(SOURCES))
    parser.add_argument('--encoding-config', type=Path, help='JSON mapping source or source/file::member to encoding')
    parser.add_argument('--batch-size', type=int, default=1000)
    args = parser.parse_args()
    raw, output = args.raw_dir.resolve(), args.output_dir.resolve()
    if not raw.is_dir():
        parser.error(f'Raw directory does not exist: {raw}')
    if raw == output or raw in output.parents or output in raw.parents:
        parser.error('Raw and output directories must be separate, non-nested directories')
    if args.batch_size < 1:
        parser.error('--batch-size must be positive')
    encodings = {}
    if args.encoding_config:
        encodings = json.loads(args.encoding_config.read_text(encoding='utf-8-sig'))
        if not isinstance(encodings, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in encodings.items()):
            parser.error('Encoding config must be a JSON object of string keys and string values')
    # Fail on missing dependencies before creating any output.
    from convert import convert_assets
    import pyarrow
    started = datetime.now(timezone.utc).isoformat()
    run = output / 'runs' / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid4().hex[:8])
    run.mkdir(parents=True, exist_ok=False)
    write_json(run / 'run.json', {'status': 'running', 'started_utc': started})
    try:
        assets, inventory_issues = inventory(raw, list(dict.fromkeys(args.sources)))
        write_json(run / 'inventory.json', assets)
        tables, conversion_issues = convert_assets(assets, run, encodings, args.batch_size)
        issues = inventory_issues + conversion_issues
        # Detect files changing during staging. Do not publish a mixed input snapshot.
        for asset in assets:
            path = Path(asset['path'])
            if not path.exists() or path.stat().st_size != asset['bytes'] or path.stat().st_mtime_ns != asset['mtime_ns']:
                issues.append({'input': asset['relative_path'], 'error': 'Input changed during this run'})
        if not tables:
            issues.append({'error': 'No CSV tables were produced'})
        write_json(run / 'inventory.json', assets)
        write_json(run / 'tables.json', tables)
        write_json(run / 'issues.json', issues)
        report = {'status': 'failed' if issues else 'complete', 'started_utc': started,
                  'finished_utc': datetime.now(timezone.utc).isoformat(), 'raw_dir': str(raw),
                  'sources': args.sources, 'tables': len(tables), 'issues': len(issues),
                  'pyarrow_version': pyarrow.__version__, 'schema_version': 1,
                  'next_stage': 'Choose geographic vintage, interpret types/missing codes, resolve facilities, then join.'}
        write_json(run / 'run.json', report)
        if not issues:
            write_json(output / 'latest_success.json', {'run_directory': str(run), **report})
        print(f"Stage 1 {report['status']}: {len(tables)} tables, {len(issues)} issues. Report: {run}")
        return 1 if issues else 0
    except Exception as exc:
        write_json(run / 'run.json', {'status': 'failed', 'started_utc': started, 'error': str(exc)})
        raise


if __name__ == '__main__':
    raise SystemExit(main())
