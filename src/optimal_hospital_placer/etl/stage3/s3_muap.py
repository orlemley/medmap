"""MUA/P component geometry overlaps, with area/population designations separated."""
import geopandas as gpd
import pandas as pd
from shapely import make_valid, union_all

from s3_common import save_table, sha256


def polygon_parts(geometry):
    if geometry.geom_type in {'Polygon', 'MultiPolygon'}:
        return geometry
    parts = [g for g in getattr(geometry, 'geoms', []) if g.geom_type in {'Polygon', 'MultiPolygon'}]
    return union_all(parts)


def load_designations(catalog, run, quality, provenance):
    path = catalog.asset('MUAP/MUA_CMPPC_SHP.zip')
    provenance.append({'file': str(path), 'sha256': sha256(path), 'role': 'MUA/P components'})
    frame = gpd.read_file(f'zip://{path.as_posix()}')
    required = ['MUASRCID', 'MUASTATD', 'MUADGNTYPD', 'MUASCORE']
    if set(required) - set(frame) or frame.crs is None:
        raise ValueError('MUA/P component schema/CRS changed; expected documented HRSA fields')
    frame = frame[required + ['geometry']].rename(columns={'MUASRCID': 'designation_id',
                    'MUASTATD': 'designation_status', 'MUADGNTYPD': 'designation_type', 'MUASCORE': 'imu_score'})
    frame['designation_id'] = frame.designation_id.astype('string').str.strip()
    if frame.designation_id.isna().any() or frame.designation_id.eq('').any():
        raise ValueError('Missing MUA/P designation ID')
    # HRSA MUASRCID is a DBF character field. The source includes both five-
    # and ten-digit IDs, also present verbatim in MUA_DET.csv. Preserve leading
    # zeros and the full identifier; never pad, truncate, or cast to integers.
    valid_ids = frame.designation_id.str.fullmatch(r'(?:[0-9]{5}|[0-9]{10})')
    if not valid_ids.all():
        examples = frame.loc[~valid_ids, 'designation_id'].drop_duplicates().head(5).tolist()
        raise ValueError(f'Unexpected MUA/P IDs: {examples}; expected five- or ten-digit text identifiers')
    active = frame.designation_status.astype('string').str.strip().str.casefold().eq('designated')
    quality['muap_inactive_components_excluded'] = int((~active).sum())
    frame = frame.loc[active].copy()
    kinds = {'medically underserved area': 'mua', 'medically underserved population': 'mup',
             "medically underserved area-governor's exception": 'mua',
             "medically underserved population-governor's exception": 'mup'}
    frame['designation_kind'] = frame.designation_type.astype('string').str.strip().str.casefold().map(kinds)
    if frame.designation_kind.isna().any():
        raise ValueError('Unrecognized active MUA/P designation type; do not conflate MUA and MUP')
    if frame.empty:
        raise ValueError('No active MUA/P components; do not publish zero coverage from an empty source')
    if frame.geometry.isna().any() or frame.geometry.is_empty.any():
        raise ValueError('Active MUA/P component lacks geometry')
    quality['muap_geometry_repairs'] = int((~frame.geometry.is_valid).sum())
    frame.geometry = frame.geometry.map(lambda g: polygon_parts(make_valid(g)))
    if frame.geometry.is_empty.any() or not frame.geometry.is_valid.all():
        raise ValueError('MUA/P component cannot be repaired to valid polygons')
    # Do not silently pick one score/type when components disagree.
    for column in ['designation_kind', 'imu_score']:
        if frame.groupby('designation_id')[column].nunique(dropna=False).gt(1).any():
            raise ValueError(f'MUA/P components disagree on {column}')
    designations = frame.to_crs(4326).dissolve(by='designation_id', as_index=False, aggfunc='first')
    save_table(designations, run / 'supporting/muap_designations.parquet')
    # Retain the tabular component records separately; no many-to-many merge into final tables.
    entry = catalog.select('MUAP/MUA_DET.csv')
    data = catalog.load(entry)
    ids = data.mua_p_id.astype('string').str.strip()
    quality['muap_shape_ids_without_csv'] = int((~designations.designation_id.isin(ids)).sum())
    save_table(data, run / 'supporting/muap_source_components.parquet')
    return designations


def overlay_features(base, key, designations, run):
    # Equal-area CRS appropriate for the selected US coverage. Areas include
    # polygon water footprint; these are NOT land-only or population fractions.
    areas = base[[key, 'geometry']].to_crs(6933)
    shapes = designations[['designation_id', 'designation_kind', 'imu_score', 'geometry']].to_crs(6933)
    intersections = gpd.overlay(areas, shapes, how='intersection', keep_geom_type=True, make_valid=False)
    intersections['overlap_area_m2'] = intersections.geometry.area
    intersections = intersections[intersections.overlap_area_m2 > 0].copy()
    denominators = areas.set_index(key).geometry.area
    intersections['boundary_area_fraction'] = intersections.overlap_area_m2 / intersections[key].map(denominators)
    # Dissolved source designations give one geometry per designation. Retain the
    # detailed relationship without duplicating rows in the final tract table.
    links = pd.DataFrame(intersections.drop(columns='geometry'))
    save_table(links, run / 'supporting' / f'muap_{key}_links.parquet')
    result = base.copy()
    for kind in ('mua', 'mup'):
        selected = intersections[intersections.designation_kind == kind]
        count = selected.groupby(key).designation_id.nunique()
        union_areas = selected.groupby(key).geometry.apply(lambda group: union_all(group.to_numpy()).area)
        fraction = union_areas / denominators.reindex(union_areas.index)
        if ((fraction < -1e-9) | (fraction > 1 + 1e-6)).any():
            raise ValueError('Invalid designation coverage fraction')
        result[f'{kind}_designation_count'] = result[key].map(count).fillna(0).astype('int64')
        result[f'{kind}_boundary_area_fraction'] = result[key].map(fraction.clip(0, 1)).fillna(0.0)
    result['muap_spatial_evaluated'] = True
    return result


def facility_links(facilities, designations, run):
    located = facilities.loc[facilities.geometry.notna(), ['facility_id', 'geometry']]
    links = gpd.sjoin(located, designations[['designation_id', 'designation_kind', 'geometry']],
                     how='inner', predicate='intersects')
    save_table(pd.DataFrame(links[['facility_id', 'designation_id', 'designation_kind']]).drop_duplicates(),
               run / 'supporting/facility_muap_links.parquet')
    result = facilities.copy()
    for kind in ('mua', 'mup'):
        members = set(links.loc[links.designation_kind == kind, 'facility_id'])
        result[f'inside_{kind}_boundary'] = pd.Series(
            [None if geometry is None else fid in members for fid, geometry in zip(result.facility_id, result.geometry)],
            index=result.index, dtype='boolean')
    return result
