"""Build tracts, counties and facilities GeoParquet; requires prepared boundaries."""
import argparse
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import geopandas as gpd
import pandas as pd

from s3_common import ROOT, STATES, Catalog, read_json, save_json, save_table, sha256
from s3_facilities import registry, geocode, assign, counts
from s3_geography import reference, align
from s3_muap import load_designations, overlay_features, facility_links


def validate(tracts, counties, facilities):
    for frame, key in [(tracts, 'tract_geoid'), (counties, 'county_geoid'), (facilities, 'facility_id')]:
        if frame[key].isna().any() or frame[key].duplicated().any():
            raise ValueError(f'Invalid final primary key: {key}')
        located = frame.geometry.dropna()
        if not located.is_valid.all() or located.is_empty.any():
            raise ValueError(f'Invalid final geometry: {key}')
    if not tracts.county_geoid.isin(counties.county_geoid).all():
        raise ValueError('Tract county foreign key mismatch')
    for key, allowed in [('tract_geoid', tracts.tract_geoid), ('county_geoid', counties.county_geoid)]:
        if not facilities[key].dropna().isin(allowed).all():
            raise ValueError(f'Facility foreign key mismatch: {key}')
    parent = tracts.set_index('tract_geoid').county_geoid
    both = facilities.tract_geoid.notna() & facilities.county_geoid.notna()
    if not facilities.loc[both, 'tract_geoid'].map(parent).eq(facilities.loc[both, 'county_geoid']).all():
        raise ValueError('Facility tract and county assignments disagree')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage2-run', type=Path)
    parser.add_argument('--boundary-dir', type=Path, default=ROOT / 'data/reference/tiger2023')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'data/stage3')
    parser.add_argument('--geocode-cache', type=Path, default=ROOT / 'data/reference/geocode_cache')
    parser.add_argument('--geocode', action='store_true', help='Send public facility addresses to Census; cache responses')
    parser.add_argument('--states', nargs='+', choices=list(STATES), default=list(STATES))
    parser.add_argument('--ahrf-columns', nargs='+', help='Reviewed stage 2 columns from the main county AHRF file')
    parser.add_argument('--crosswalks', type=Path, help='JSON reviewed one-to-one identifier equivalences; no areal interpolation')
    args = parser.parse_args()
    states = list(dict.fromkeys(args.states))
    stage2 = args.stage2_run or Path(read_json(ROOT / 'data/stage2/latest_success.json')['run_directory'])
    catalog = Catalog(stage2)
    crosswalks = read_json(args.crosswalks) if args.crosswalks else {}
    if not isinstance(crosswalks, dict) or set(crosswalks) - {e['input'] for e in catalog.entries}:
        parser.error('Crosswalks must map known exact source identities to lists of equivalences')
    for rows in crosswalks.values():
        if not isinstance(rows, list) or any(not isinstance(r, dict) or set(r) != {'source_geoid', 'target_geoid', 'evidence'}
                                          or not all(isinstance(v, str) and v.strip() for v in r.values()) for r in rows):
            parser.error('Crosswalk records must contain nonempty source_geoid, target_geoid and evidence strings')
    output = args.output_dir.resolve()
    boundaries = args.boundary_dir.resolve()
    cache = args.geocode_cache.resolve()
    for protected in (ROOT / 'data/raw', ROOT / 'data/stage1', ROOT / 'data/stage2', catalog.run, boundaries, cache):
        protected = protected.resolve()
        if output == protected or output in protected.parents or protected in output.parents:
            parser.error('Output directory must be separate from inputs and caches')
    run = output / 'runs' / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid4().hex[:8])
    run.mkdir(parents=True, exist_ok=False)
    status = {'status': 'running', 'stage2_run': str(catalog.run), 'states': states,
              'geography_vintage': 2023, 'started_utc': datetime.now(timezone.utc).isoformat(),
              'geocoding_requested': args.geocode, 'ahrf_columns': args.ahrf_columns}
    save_json(run / 'manifest.json', status)
    save_json(run / 'crosswalks.json', crosswalks)
    quality, inputs = {'alignments': []}, []
    try:
        print('Loading 2023 reference geography', flush=True)
        tracts, counties = reference(boundaries, states, inputs)
        original_counts = (len(tracts), len(counties))
        print('Aligning source attributes by exact identifiers', flush=True)
        tracts = align(tracts, catalog, 'PLACES/places_tract.csv', 'tractfips', 'tract_geoid', 'places', 2023, run, quality['alignments'], crosswalks=crosswalks)
        counties = align(counties, catalog, 'PLACES/places_county.csv', 'countyfips', 'county_geoid', 'places', 2023, run, quality['alignments'], crosswalks=crosswalks)
        tracts = align(tracts, catalog, 'SVI/SVI_2022_US.csv', 'fips', 'tract_geoid', 'svi', 2022, run, quality['alignments'], crosswalks=crosswalks)
        counties = align(counties, catalog, 'SVI/SVI_2022_US_county.csv', 'fips', 'county_geoid', 'svi', 2022, run, quality['alignments'], crosswalks=crosswalks)
        tracts = align(tracts, catalog, 'RUCA/*census-tracts.csv', 'tractfips23', 'tract_geoid', 'ruca', 2023, run, quality['alignments'], crosswalks=crosswalks)
        if args.ahrf_columns:
            counties = align(counties, catalog, 'AHRF/*CSV.zip::*/AHRF2025.csv', 'fips_st_cnty', 'county_geoid',
                             'ahrf', 'source_definition_not_verified', run, quality['alignments'], args.ahrf_columns, crosswalks)
        else:
            # Publish known county classifications as strings; never choose among
            # historical workforce/bed measures without a reviewed variable list.
            counties = align(counties, catalog, 'AHRF/*CSV.zip::*/AHRF2025geo.csv', 'fips_st_cnty', 'county_geoid',
                             'ahrf', 'source_definition_not_verified', run, quality['alignments'],
                             ['fips_st_cnty', 'rural_urban_contnm_23', 'hpsa_prim_care_25', 'hpsa_dent_25', 'hpsa_mentl_hlth_25'], crosswalks)
        print('Building facility registry', flush=True)
        facilities = registry(catalog, states, run)
        facilities = assign(geocode(facilities, cache, args.geocode), tracts, counties)
        print('Overlaying MUA/P component boundaries', flush=True)
        designations = load_designations(catalog, run, quality, inputs)
        tracts = overlay_features(tracts, 'tract_geoid', designations, run)
        counties = overlay_features(counties, 'county_geoid', designations, run)
        facilities = facility_links(facilities, designations, run)
        tracts = counts(tracts, facilities, 'tract_geoid')
        counties = counts(counties, facilities, 'county_geoid')
        # HPSA rows are components, not a one-row-per-tract table. Keep them intact
        # until a reviewed component-geography adapter is supplied.
        for entry in catalog.entries:
            if entry['source'] == 'HPSA':
                save_table(catalog.load(entry), run / 'supporting' / ('hpsa_' + Path(entry['input']).stem + '.parquet'))
        if original_counts != (len(tracts), len(counties)):
            raise ValueError('Reference row conservation failed')
        validate(tracts, counties, facilities)
        quality.update(facility_count=len(facilities), facilities_unlocated=int(facilities.geometry.isna().sum()),
                       facilities_without_tract=int(facilities.tract_geoid.isna().sum()),
                       facilities_with_conflicts=int(facilities.field_conflicts.notna().sum()),
                       facilities_with_shared_ccn=int(facilities.ccn_multiple_locations.sum()),
                       limitations=['Exact-identifier joins do not reallocate changed boundaries; unmatched records retained.',
                                    'Facility status and same-provider alternative addresses require review; counts are registry counts.',
                                    'Census geocodes are interpolated street locations, not verified entrances.',
                                    'MUA/P fractions measure boundary footprint, including water, not population or land-only coverage.',
                                    'HPSA component records retained separately; no tract HPSA coverage inferred.',
                                    'AHRF feature selection is limited unless --ahrf-columns is supplied.'])
        artifacts, dictionary = {}, {}
        for name, frame in [('tracts', tracts), ('counties', counties), ('facilities', facilities)]:
            path = run / f'{name}.parquet'
            save_table(frame, path)
            check = gpd.read_parquet(path)
            if len(check) != len(frame) or check.crs is None or check.columns.tolist() != frame.columns.tolist():
                raise ValueError(f'GeoParquet round-trip metadata mismatch: {name}')
            artifacts[name] = {'path': path.name, 'rows': len(frame), 'sha256': sha256(path)}
            dictionary[name] = {c: {'dtype': str(frame[c].dtype), 'origin': 'source_attribute' if c.startswith(('svi_', 'places_', 'ruca_', 'ahrf_')) else 'reference_or_derived',
                                    'measurement_year': None} for c in frame if c != 'geometry'}
        save_json(run / 'quality_report.json', quality)
        save_json(run / 'data_dictionary.json', dictionary)
        save_json(run / 'source_inventory.json', catalog.inventory)
        save_json(run / 'source_tables.json', list(catalog.used.values()))
        # Rule/unit/measurement-year sidecars are carried forward without inferring years.
        for entry in catalog.used.values():
            report_path = (catalog.run / entry['report']).resolve()
            if catalog.run not in report_path.parents:
                raise ValueError('Stage 2 report path escapes run')
            save_json(run / 'source_reports' / report_path.name, read_json(report_path))
        status.update(status='complete_with_review_items', outputs=artifacts, inputs=inputs,
                      finished_utc=datetime.now(timezone.utc).isoformat())
        save_json(run / 'manifest.json', status)
        save_json(output / 'latest_success.json', {'run_directory': str(run), **status})
        print(f'Published {run}. Read quality_report.json before analysis.')
        return 0
    except Exception as exc:
        status.update(status='failed', error=str(exc))
        save_json(run / 'manifest.json', status)
        save_json(run / 'quality_report.json', quality)
        raise


if __name__ == '__main__':
    raise SystemExit(main())
