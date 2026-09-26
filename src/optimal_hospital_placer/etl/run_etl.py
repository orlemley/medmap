"""Run stages 1–3 followed by ACS download, preparation, and stage 4 enrichment."""
import argparse
import json
from pathlib import Path
import subprocess
import sys


ETL = Path(__file__).resolve().parent
ROOT = ETL.parents[2]


def run_stage(number, arguments):
    output = ROOT / 'data' / f'stage{number}'
    pointer = output / 'latest_success.json'
    previous = pointer.read_bytes() if pointer.exists() else None
    command = [sys.executable, '-u', str(ETL / f'stage{number}' / f'run_stage{number}.py'),
               *map(str, arguments)]
    print(f'\n=== Stage {number} of 4 ===', flush=True)
    subprocess.run(command, check=True)
    # Do not silently hand an older successful snapshot to the next stage.
    current = pointer.read_bytes()
    if current == previous:
        raise RuntimeError(f'Stage {number} did not publish a new successful run')
    run = Path(json.loads(current)['run_directory'])
    if not run.is_dir():
        raise RuntimeError(f'Stage {number} published a missing run directory: {run}')
    return run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--geocode', action='store_true',
                        help='Allow stage 3 to request uncached Census geocodes')
    parser.add_argument('--states', nargs='+', help='Stage 3 state FIPS codes, e.g. 17 18; default: all states and DC')
    parser.add_argument('--boundary-dir', type=Path, default=ROOT / 'data/reference/tiger2023')
    parser.add_argument('--geocode-cache', type=Path, default=ROOT / 'data/reference/geocode_cache')
    parser.add_argument('--skip-acs-download', action='store_true',
                        help='Require existing ACS downloads instead of downloading missing files')
    args = parser.parse_args()
    stage3_args = ['--boundary-dir', args.boundary_dir.resolve(),
                   '--geocode-cache', args.geocode_cache.resolve()]
    if args.geocode:
        stage3_args.append('--geocode')
    if args.states:
        stage3_args.extend(['--states', *args.states])
    try:
        stage1 = run_stage(1, [])
        stage2 = run_stage(2, ['--stage1-run', stage1])
        stage3 = run_stage(3, ['--stage2-run', stage2, *stage3_args])
        print('\n=== Stage 4 of 4: ACS enrichment ===', flush=True)
        command = [sys.executable, '-u', str(ETL / 'acs/run_acs.py'), '--stage3-run', str(stage3)]
        if args.skip_acs_download:
            command.append('--skip-download')
        subprocess.run(command, check=True)
        published = json.loads((ROOT / 'data/stage4/latest_success.json').read_text(encoding='utf-8-sig'))
        stage4 = Path(published['run_directory'])
        if published.get('status') != 'complete' or Path(published['stage3_run']).resolve() != stage3.resolve() or not stage4.is_dir():
            raise RuntimeError('Stage 4 did not publish enrichment for this stage 3 snapshot')
    except subprocess.CalledProcessError as exc:
        print(f'\nETL stopped: a stage failed (exit code {exc.returncode}). See its output above.', file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        print(f'\nETL stopped: {exc}', file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print('\nETL interrupted.', file=sys.stderr)
        return 130
    print(f'\nETL complete. Final Parquet files: {stage4}', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
