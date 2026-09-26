"""Run ACS download, preparation, and enrichment; never invokes stages 1-3."""
import argparse
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage3-run', type=Path, help='Defaults to stage 3 latest_success.json')
    parser.add_argument('--skip-download', action='store_true', help='Offline; require downloaded files with receipts')
    args = parser.parse_args()
    from acs_common import ROOT, YEAR, read
    stage3 = (args.stage3_run or Path(read(ROOT / 'data/stage3/latest_success.json')['run_directory'])).resolve()
    report = read(stage3 / 'manifest.json')
    if report.get('status') not in {'complete', 'complete_with_review_items'} or report.get('geography_vintage') != YEAR:
        parser.error('Requires a successful stage 3 run with 2023 reference geography')
    if not args.skip_download:
        from download_acs import download
        download()
    from prepare_acs import prepare
    prepared = prepare()
    from enrich_acs import enrich
    output = enrich(stage3, prepared)
    print(f'ACS enrichment complete: {output}', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
