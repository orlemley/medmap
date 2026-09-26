"""Join prepared ACS attributes onto a completed stage 3 snapshot, without spatial work."""
import argparse
from pathlib import Path
import shutil

import geopandas as gpd
import pandas as pd

from acs_common import (ROOT, YEAR, OUTPUT, PREPARED, code_hash, complete, fingerprint,
                        read, reusable, save, sha)


def enrich(stage3_run=None, acs_run=None):
    stage3 = Path(stage3_run or read(ROOT / 'data/stage3/latest_success.json')['run_directory']).resolve()
    acs = Path(acs_run or read(PREPARED / 'latest_success.json')['run_directory']).resolve()
    source = read(stage3 / 'manifest.json')
    prepared = read(acs / 'manifest.json')
    if source.get('status') not in {'complete', 'complete_with_review_items'}:
        raise ValueError('A successful stage 3 snapshot is required')
    if source.get('geography_vintage') != YEAR or prepared.get('year') != YEAR:
        raise ValueError('This adapter only supports ACS 2023 joined to 2023 reference geography')
    if not reusable(acs, prepared.get('identity')):
        raise ValueError('ACS preparation snapshot failed checksum validation')
    stage3_hashes = {}
    for name in ['tracts', 'counties', 'facilities']:
        digest = sha(stage3 / f'{name}.parquet')
        if source['outputs'][name]['sha256'] != digest:
            raise ValueError(f'Stage 3 checksum mismatch: {name}')
        stage3_hashes[name] = digest
    # Include supporting provenance in the checkpoint identity too.
    for name in ['manifest.json', 'data_dictionary.json', 'quality_report.json']:
        stage3_hashes[name] = sha(stage3 / name)
    identity = {'stage3_run': str(stage3), 'stage3_hashes': stage3_hashes,
                'acs_run': str(acs), 'acs_manifest': sha(acs / 'manifest.json'),
                'code': code_hash('enrich_acs.py')}
    run = OUTPUT / 'runs' / fingerprint(identity)
    if reusable(run, identity):
        print(f'Using completed ACS enrichment: {run}', flush=True)
        save(OUTPUT / 'latest_success.json', {'run_directory': str(run), **read(run / 'manifest.json')})
        return run
    run.mkdir(parents=True, exist_ok=True)
    save(run / 'manifest.json', {'status': 'running', 'identity': identity})
    try:
        report, artifacts = {}, []
        dictionary = read(stage3 / 'data_dictionary.json')
        acs_dictionary = read(acs / 'data_dictionary.json')
        for name, key, width in [('tracts', 'tract_geoid', 11), ('counties', 'county_geoid', 5)]:
            print(f'Joining ACS onto {name}; no spatial processing', flush=True)
            base = gpd.read_parquet(stage3 / f'{name}.parquet')
            attributes = pd.read_parquet(acs / f'acs_{name}.parquet')
            for label, frame in [('stage3', base), ('ACS', attributes)]:
                if (frame[key].isna().any() or frame[key].duplicated().any()
                        or not frame[key].astype('string').str.fullmatch(rf'[0-9]{{{width}}}').all()):
                    raise ValueError(f'{label}: invalid/duplicate {key}')
                if not frame[key].map(lambda value: isinstance(value, str)).all():
                    raise ValueError(f'{label}: {key} must already be text')
            collisions = (set(base) & set(attributes)) - {key}
            if collisions or 'acs_geography_matched' in base:
                raise ValueError(f'ACS columns already present: {sorted(collisions)}')
            missing = base.loc[~base[key].isin(attributes[key]), [key]]
            if len(missing) == len(base):
                raise ValueError(f'No ACS {name} IDs match stage 3')
            # Restrict unused-source reporting to selected state prefixes.
            selected_states = set(base[key].str[:2])
            unused = attributes.loc[attributes[key].str[:2].isin(selected_states)
                                    & ~attributes[key].isin(base[key]), [key]]
            for label, frame in [('without_acs', missing), ('acs_without_reference', unused)]:
                filename = f'{name}_{label}.parquet'
                frame.to_parquet(run / filename, index=False)
                artifacts.append(filename)
            joined = base.merge(attributes, on=key, how='left', validate='one_to_one', sort=False)
            joined['acs_geography_matched'] = joined[key].isin(attributes[key])
            if (len(joined) != len(base) or not joined[key].equals(base[key])
                    or joined.crs != base.crs or not joined.geometry.to_wkb().equals(base.geometry.to_wkb())):
                raise ValueError(f'ACS join changed reference rows/order/geometry: {name}')
            joined.to_parquet(run / f'{name}.parquet', index=False, compression='zstd')
            check = gpd.read_parquet(run / f'{name}.parquet')
            if len(check) != len(base) or check.crs != base.crs or not check[key].equals(base[key]):
                raise ValueError(f'GeoParquet readback failed: {name}')
            artifacts.append(f'{name}.parquet')
            report[name] = {'reference_rows': len(base), 'matched': len(base) - len(missing),
                            'reference_without_acs': len(missing), 'acs_without_reference_in_selected_states': len(unused),
                            'missing_table_records': {c: int((~joined[c].fillna(False).astype(bool)).sum())
                                                      for c in attributes if c.endswith('_record_present')}}
            for column in joined:
                if column.startswith('acs_'):
                    info = acs_dictionary.get(column)
                    if info is None and column.endswith('_annotation'):
                        info = {'kind': 'original_special_value_token', 'value_column': column.removesuffix('_annotation')}
                    dictionary[name][column] = info or {'kind': 'ACS provenance or record availability', 'release_year': YEAR}
        # Byte-for-byte carry-forward; no registry, geocoding, or overlays.
        shutil.copyfile(stage3 / 'facilities.parquet', run / 'facilities.parquet')
        if sha(run / 'facilities.parquet') != stage3_hashes['facilities']:
            raise ValueError('Facility copy checksum mismatch')
        for origin, name in [(stage3 / 'quality_report.json', 'stage3_quality_report.json'),
                             (stage3 / 'manifest.json', 'stage3_manifest.json'),
                             (acs / 'manifest.json', 'acs_manifest.json'),
                             (acs / 'issues.json', 'acs_issues.json')]:
            shutil.copyfile(origin, run / name)
            artifacts.append(name)
        report['alignment_method'] = 'Exact GEOID, same release/reference year; no interpolation or renumbering'
        report['review_required'] = True
        report['limitations'] = ['Same-year ID matches do not independently establish boundary equivalence.',
                                'Missing/thresholded ACS values remain null with original tokens retained.',
                                'Stage 3 quality limitations still apply. No derived rates or scores added.']
        save(run / 'acs_join_report.json', report)
        save(run / 'data_dictionary.json', dictionary)
        complete(run, identity, artifacts + ['facilities.parquet', 'acs_join_report.json', 'data_dictionary.json'],
                 year=YEAR, review_required=True, stage3_run=str(stage3), acs_run=str(acs))
        save(OUTPUT / 'latest_success.json', {'run_directory': str(run), **read(run / 'manifest.json')})
        return run
    except Exception as exc:
        save(run / 'manifest.json', {'status': 'failed', 'identity': identity, 'error': str(exc)})
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage3-run', type=Path)
    parser.add_argument('--acs-run', type=Path)
    args = parser.parse_args()
    print(enrich(args.stage3_run, args.acs_run))
