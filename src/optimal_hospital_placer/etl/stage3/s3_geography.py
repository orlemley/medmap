"""Reference polygons and one-to-one source joins; no inferred crosswalks."""
import geopandas as gpd
import pandas as pd

from s3_common import read_json, save_table, sha256


def polygons(path):
    frame = gpd.read_file(f'zip://{path.as_posix()}')
    if frame.crs is None or frame.geometry.isna().any() or frame.geometry.is_empty.any():
        raise ValueError(f'Missing CRS/geometry: {path}')
    if not frame.geometry.is_valid.all():
        raise ValueError(f'Invalid reference geometry: {path}; review rather than silently repair')
    if not frame.geom_type.isin(['Polygon', 'MultiPolygon']).all():
        raise ValueError(f'Expected polygons: {path}')
    return frame.to_crs(4326)


def reference(directory, states, provenance):
    def load(name):
        path = directory / name
        if not path.exists():
            raise ValueError(f'Missing {path}. Run prepare_boundaries.py first.')
        digest = sha256(path)
        receipt = directory / f'{name}.receipt.json'
        if receipt.exists() and read_json(receipt)['sha256'] != digest:
            raise ValueError(f'Boundary checksum mismatch: {path}')
        provenance.append({'file': str(path), 'sha256': digest, 'vintage': 2023})
        return polygons(path)
    county = load('tl_2023_us_county.zip')
    county = county[county.STATEFP.isin(states)].copy()
    tract = gpd.GeoDataFrame(pd.concat([load(f'tl_2023_{s}_tract.zip') for s in states], ignore_index=True), crs=4326)
    def shape(frame, key):
        columns = ['GEOID', 'STATEFP', 'NAME', 'ALAND', 'AWATER', 'geometry']
        result = frame[columns].rename(columns={'GEOID': key, 'STATEFP': 'state_fips', 'NAME': 'name',
                                               'ALAND': 'land_area_m2', 'AWATER': 'water_area_m2'})
        result['geography_vintage'] = 2023
        if result[key].isna().any() or result[key].duplicated().any():
            raise ValueError(f'Invalid reference key: {key}')
        if not result[key].str.fullmatch(r'\d{' + ('11' if key == 'tract_geoid' else '5') + '}').all():
            raise ValueError(f'Malformed reference GEOID: {key}')
        return result
    tracts, counties = shape(tract, 'tract_geoid'), shape(county, 'county_geoid')
    tracts['county_geoid'] = tract.STATEFP + tract.COUNTYFP
    if not tracts.county_geoid.isin(counties.county_geoid).all():
        raise ValueError('Tract county foreign key is absent from reference')
    return tracts, counties


def align(base, catalog, pattern, source_key, target_key, prefix, vintage, run, quality, selected=None, crosswalks=None):
    entry = catalog.select(pattern)
    data = catalog.load(entry)
    if source_key not in data:
        raise ValueError(f'Missing key {source_key} in {entry["input"]}')
    raw_key = data[source_key].astype('string').str.strip()
    aligned_key = raw_key.copy()
    mapping = (crosswalks or {}).get(entry['input'], [])
    if mapping:
        mapping = pd.DataFrame(mapping)
        required = {'source_geoid', 'target_geoid', 'evidence'}
        if set(mapping) != required or mapping[list(required)].isna().any().any():
            raise ValueError('Crosswalk requires source_geoid, target_geoid and evidence')
        if mapping.source_geoid.duplicated().any() or mapping.target_geoid.duplicated().any():
            raise ValueError('Only one-to-one identifier-equivalence crosswalks are supported')
        if not mapping.source_geoid.isin(raw_key).all():
            raise ValueError('Crosswalk contains source IDs absent from the source table')
        if not mapping.target_geoid.isin(base[target_key]).all():
            raise ValueError('Crosswalk target absent from selected reference geography')
        lookup = mapping.set_index('source_geoid').target_geoid
        aligned_key = raw_key.map(lookup).fillna(raw_key)
        save_table(mapping, run / 'supporting' / f'{prefix}_{target_key}_crosswalk.parquet')
    length = 11 if target_key == 'tract_geoid' else 5
    valid = raw_key.str.fullmatch(r'\d{' + str(length) + '}', na=False)
    in_scope = raw_key.str[:2].isin(base.state_fips.unique())
    matched = valid & aligned_key.isin(base[target_key])
    rejected = data.loc[~matched].copy()
    rejected['_stage3_alignment_reason'] = 'outside_selected_states'
    rejected.loc[~valid, '_stage3_alignment_reason'] = 'malformed_identifier'
    rejected.loc[valid & in_scope & ~matched, '_stage3_alignment_reason'] = 'no_exact_2023_identifier'
    save_table(rejected, run / 'supporting' / f'{prefix}_{target_key}_unmatched.parquet')
    if aligned_key[matched].duplicated().any():
        raise ValueError(f'{entry["input"]}: duplicate matched identifiers; no automatic aggregation')
    columns = list(dict.fromkeys(selected)) if selected is not None else [c for c in data if not c.startswith('_stage2_')]
    if set(columns) - set(data):
        raise ValueError(f'Unknown requested columns: {set(columns) - set(data)}')
    frame = data.loc[matched, columns].copy()
    frame = frame.rename(columns={c: f'{prefix}_{c}' for c in frame})
    frame[target_key] = aligned_key[matched]
    frame[f'{prefix}_matched'] = True
    frame[f'{prefix}_source_geography_vintage'] = vintage
    frame[f'{prefix}_match_method'] = 'exact_identifier_no_reallocation'
    frame.loc[raw_key[matched] != aligned_key[matched], f'{prefix}_match_method'] = 'reviewed_identifier_equivalence'
    output = base.merge(frame, on=target_key, how='left', validate='one_to_one')
    output[f'{prefix}_matched'] = output[f'{prefix}_matched'].fillna(False).astype(bool)
    quality.append({'source': entry['input'], 'prefix': prefix, 'target': target_key, 'method': 'exact_identifier_or_reviewed_equivalence',
                    'crosswalk_rows': len(mapping),
                    'source_vintage': vintage, 'matched': int(matched.sum()),
                    'unmatched_in_scope': int((valid & in_scope & ~matched).sum()),
                    'malformed_identifiers': int((~valid).sum()),
                    'reference_without_source': int((~output[f'{prefix}_matched']).sum())})
    return output
