"""Prepare typed source tables before geography; Python 3.10+. No network access."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def main():
    root = Path(__file__).resolve().parents[4]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage1-dir', type=Path, default=root / 'data/stage1')
    parser.add_argument('--stage1-run', type=Path, help='Explicit completed run; otherwise use latest_success.json')
    parser.add_argument('--output-dir', type=Path, default=root / 'data/stage2')
    parser.add_argument('--rules', type=Path, help='Optional reviewed column rules as JSON')
    parser.add_argument('--batch-size', type=int, default=1000)
    args = parser.parse_args()
    if args.batch_size < 1:
        parser.error('--batch-size must be positive')
    from stage2_transform import transform, save
    from stage2_rules import VERSION
    import pyarrow
    stage1 = args.stage1_run
    if stage1 is None:
        stage1 = Path(read(args.stage1_dir / 'latest_success.json')['run_directory'])
    stage1 = stage1.resolve()
    report = read(stage1 / 'run.json')
    if report.get('status') != 'complete' or report.get('issues') != 0:
        parser.error('Stage 2 requires a completed stage 1 run with zero issues')
    entries = read(stage1 / 'tables.json')
    if not entries or len(entries) != report['tables']:
        parser.error('Stage 1 table manifest is empty or inconsistent')
    identities = [entry['input'] for entry in entries]
    if len(set(identities)) != len(identities):
        parser.error('Duplicate source identities in stage 1 manifest')
    output = args.output_dir.resolve()
    # Protect both previous-stage and raw directories from accidental output writes.
    for protected in (args.stage1_dir.resolve(), stage1, Path(report['raw_dir']).resolve()):
        if output == protected or output in protected.parents or protected in output.parents:
            parser.error('Output directory must be separate from raw data and stage 1')
    rules = read(args.rules) if args.rules else {}
    if not isinstance(rules, dict) or set(rules) - {'sources', 'tables'}:
        parser.error('Rules must be an object with sources and/or tables mappings')
    # Reject misspelled overrides instead of quietly failing to apply them.
    for scope, mapping in rules.items():
        if not isinstance(mapping, dict):
            parser.error(f'{scope} must be an object')
        for key, columns in mapping.items():
            matches = [e for e in entries if e['source' if scope == 'sources' else 'input'] == key]
            known = {c['normalized'] for e in matches for c in e['column_map']}
            if not matches or not isinstance(columns, dict) or set(columns) - known:
                parser.error(f'Unknown table/source/columns in override: {key}')
            allowed = {'type', 'missing', 'minimum', 'maximum', 'unit', 'measurement_year'}
            if any(not isinstance(v, dict) or set(v) - allowed for v in columns.values()):
                parser.error(f'Invalid column rule in {key}')
    run = output / 'runs' / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid4().hex[:8])
    run.mkdir(parents=True, exist_ok=False)
    status = {'status': 'running', 'started_utc': datetime.now(timezone.utc).isoformat(),
              'stage1_run': str(stage1), 'sources': report.get('sources'), 'rules_version': VERSION,
              'pyarrow_version': pyarrow.__version__, 'geography_aligned': False}
    save(run / 'run.json', status)
    save(run / 'rules_overrides.json', rules)
    tables, issues = [], []
    try:
        # Preserve access to source receipts, documentation, and metadata for stage 3.
        save(run / 'source_inventory.json', read(stage1 / 'inventory.json'))
        for entry in entries:
            print(f"Preparing {entry['input']}", flush=True)
            try:
                tables.append(transform(entry, stage1, run, rules, args.batch_size))
            except Exception as exc:
                issues.append({'input': entry['input'], 'error': str(exc)})
            save(run / 'tables.json', tables)
            save(run / 'issues.json', issues)
        status.update(status='failed' if issues else 'complete', tables=len(tables), issues=len(issues),
                      finished_utc=datetime.now(timezone.utc).isoformat(),
                      warning_cells=sum(t['warning_cells'] for t in tables),
                      review_required_columns=sum(t['review_required_columns'] for t in tables))
        save(run / 'run.json', status)
        if not issues:
            save(output / 'latest_success.json', {'run_directory': str(run), **status})
        print(f"Stage 2 {status['status']}: {len(tables)} tables, {len(issues)} issues, "
              f"{status['warning_cells']} warned cells. Reports: {run}")
        return 1 if issues else 0
    except Exception as exc:
        status.update(status='failed', error=str(exc))
        save(run / 'run.json', status)
        raise


if __name__ == '__main__':
    raise SystemExit(main())
