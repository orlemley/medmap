"""Conservative CCN/address registry, optional cached Census geocoding, assignments."""
import csv
import hashlib
import io
import json
import math
import re
import time
from datetime import datetime, timezone

import geopandas as gpd
import pandas as pd
import requests
from shapely.geometry import Point

from s3_common import STATES, read_json, save_json, save_table, text
from s3_geocode_fallbacks import enrich_hospital_geocodes


def request_geocode_batch(payload, benchmark, batch_number):
    """Make a bounded best-effort Census request."""
    attempts = 2
    retry_statuses = {408, 429, 500, 502, 503, 504}
    for attempt in range(1, attempts + 1):
        response = None
        try:
            response = requests.post(
                'https://geocoding.geo.census.gov/geocoder/locations/addressbatch',
                files={'addressFile': ('addresses.csv', payload, 'text/csv')},
                data={'benchmark': benchmark}, timeout=(10, 60))
            response.raise_for_status()
            return response
        except (requests.Timeout, requests.ConnectionError, requests.HTTPError) as exc:
            if isinstance(exc, requests.HTTPError) and (
                    response is None or response.status_code not in retry_statuses):
                if response is not None:
                    response.close()
                raise
            if response is not None:
                response.close()
            if attempt == attempts:
                print(f'Geocoding batch {batch_number} failed after {attempts} attempts. '
                      'Leaving this batch unresolved; completed batches remain cached.', flush=True)
                raise
            delay = 5 * attempt
            print(f'Geocoding batch {batch_number}: attempt {attempt}/{attempts} failed '
                  f'({exc}). Retrying the same batch in {delay} seconds.', flush=True)
            time.sleep(delay)


def normalized(value):
    return re.sub(r'\s+', ' ', text(value).upper())


def first(row, *keys):
    for key in keys:
        value = row.get(key)
        if text(value):
            return value
    return None


def registry(catalog, states, run):
    records = []
    for entry in catalog.entries:
        if entry['source'] not in {'CMSHospital', 'CMSFacilities'}:
            continue
        source = catalog.load(entry)
        needed = {'state', 'enrollment_state', 'state_cd', 'facility_id', 'ccn', 'prvdr_num',
                  'address', 'address_line_1', 'address_line_2', 'st_adr', 'city_town', 'city', 'city_name',
                  'zip_code', 'zip_cd', '_stage2_source_row', 'npi', 'enrollment_id', 'facility_name',
                  'organization_name', 'fac_name', 'hospital_ownership', 'proprietary_nonprofit',
                  'emergency_services', 'hospital_overall_rating', 'bed_cnt', 'pgm_trmntn_cd',
                  'cmplnc_stus_cd', 'prvdr_ctgry_cd', 'prvdr_type_id', 'provider_type_text'}
        source = source[[c for c in source if c in needed]]
        for row in source.to_dict('records'):
            state = normalized(first(row, 'state', 'enrollment_state', 'state_cd'))
            if state not in {STATES[s] for s in states}:
                continue
            ccn = normalized(first(row, 'facility_id', 'ccn', 'prvdr_num'))
            street = text(first(row, 'address', 'address_line_1', 'st_adr'))
            street2 = text(first(row, 'address_line_2'))
            city = text(first(row, 'city_town', 'city', 'city_name'))
            postal = text(first(row, 'zip_code', 'zip_cd'))
            postal5 = postal[:5] if re.fullmatch(r'\d{5}(?:-?\d{4})?', postal) else postal
            address_key = '|'.join(map(normalized, [street, street2, city, state, postal5]))
            row_id = int(row['_stage2_source_row'])
            identity = f'{entry["input"]}::{row_id}'
            # No fuzzy merge or name-only merge. Different suites remain separate.
            key = f'ccn:{ccn}|{address_key}' if ccn and street and city and postal5 else identity
            fid = 'facility_' + hashlib.sha256(key.encode()).hexdigest()[:24]
            label = 'unclassified_provider'
            for fragment, kind in [('Hospital_Enrollments', 'hospital'), ('FQHC_', 'fqhc'), ('SNF_', 'skilled_nursing'),
                                   ('RHC_', 'rural_health_clinic'), ('Hospice_', 'hospice'), ('HHA_', 'home_health')]:
                if fragment in entry['input']:
                    label = kind
            if entry['source'] == 'CMSHospital':
                label = 'hospital'
            beds = row.get('bed_cnt')
            records.append({'facility_id': fid, 'source_table': entry['input'], 'source_row': row_id,
                            'ccn': ccn or None, 'npi': text(row.get('npi')) or None,
                            'enrollment_id': text(row.get('enrollment_id')) or None,
                            'name': text(first(row, 'facility_name', 'organization_name', 'fac_name')),
                            'street': street, 'street2': street2, 'city': city, 'state': state, 'zip': postal5,
                            'facility_type': label, 'ownership': text(first(row, 'hospital_ownership', 'proprietary_nonprofit')) or None,
                            'emergency_services': row.get('emergency_services'),
                            'hospital_overall_rating': row.get('hospital_overall_rating'),
                            'bed_count': beds if beds is not None and not pd.isna(beds) else None,
                            'source_status_code': text(first(row, 'pgm_trmntn_cd', 'cmplnc_stus_cd')) or None,
                            'source_category_code': text(first(row, 'prvdr_ctgry_cd', 'prvdr_type_id')) or None,
                            'source_provider_type_text': text(row.get('provider_type_text')) or None,
                            'match_method': 'exact_ccn_and_address' if key != identity else 'unmerged_source_record',
                            'priority': 0 if entry['source'] == 'CMSHospital' else (1 if 'Enrollments' in entry['input'] else 2)})
    if not records:
        raise ValueError('No facility records found in selected states')
    links = pd.DataFrame(records).sort_values(['priority', 'source_table', 'source_row'])
    facilities = []
    value_fields = ['ccn', 'name', 'street', 'street2', 'city', 'state', 'zip', 'ownership',
                    'emergency_services', 'hospital_overall_rating', 'bed_count']
    for fid, group in links.groupby('facility_id', sort=True):
        result = {'facility_id': fid, 'source_record_count': len(group)}
        conflicts = {}
        for field in value_fields:
            values = [v for v in group[field] if text(v)]
            distinct = list(dict.fromkeys(text(v) for v in values))
            result[field] = values[0] if values else None
            if len(distinct) > 1:
                conflicts[field] = distinct
                # Do not manufacture a single capacity when sources disagree.
                if field == 'bed_count':
                    result[field] = None
        kinds = set(group.facility_type) - {'unclassified_provider'}
        result['facility_type'] = next(iter(kinds)) if len(kinds) == 1 else 'unclassified_provider'
        if len(kinds) > 1:
            conflicts['facility_type'] = sorted(kinds)
        result['field_conflicts'] = json.dumps(conflicts) if conflicts else None
        result['operating_status'] = 'not_adjudicated'
        result['care_site_role'] = ('office_or_service_site_unresolved' if result['facility_type'] in {'hospice', 'home_health', 'unclassified_provider'}
                                    else 'reported_care_site')
        result['match_method'] = group.iloc[0].match_method
        facilities.append(result)
    frame = pd.DataFrame(facilities)
    # Repeated CCNs at different addresses remain separate; expose them for review.
    frame['ccn_multiple_locations'] = frame.ccn.notna() & frame.ccn.duplicated(keep=False)
    for field in ['bed_count', 'hospital_overall_rating']:
        frame[field] = pd.to_numeric(frame[field], errors='raise').astype('Float64')
    frame['emergency_services'] = frame.emergency_services.astype('boolean')
    save_table(links.drop(columns='priority'), run / 'supporting/facility_source_records.parquet')
    return frame


def geocode(frame, cache_dir, enabled, catalog=None, quality=None, network_fallbacks=False):
    cache_dir.mkdir(parents=True, exist_ok=True)
    benchmark = 'Public_AR_Current'
    address_keys, pending, cache = {}, {}, {}
    # Downstream access modeling and the current map consume hospital locations.
    # Keep the complete registry, but avoid issuing and loading address-cache
    # records for the much larger set of non-hospital providers.
    hospitals = frame.loc[frame.facility_type.eq('hospital')]
    print(f'Geocoding hospitals only: {len(hospitals):,} of {len(frame):,} registry facilities', flush=True)
    for row in hospitals.to_dict('records'):
        address = [text(row[c]) for c in ('street', 'city', 'state', 'zip')]
        # Census returns street-interpolated locations, not guaranteed entrances.
        key = hashlib.sha256(json.dumps([benchmark, address]).encode()).hexdigest()
        address_keys[row['facility_id']] = key
        path = cache_dir / f'{key}.json'
        if path.exists():
            item = read_json(path)
            if item.get('address') != address or item.get('benchmark') != benchmark:
                raise ValueError(f'Geocoding cache identity mismatch: {path}')
            if item.get('status') == 'Match':
                lon, lat = item.get('longitude'), item.get('latitude')
                if not isinstance(lon, (int, float)) or not isinstance(lat, (int, float)) or not (-180 <= lon <= 180 and -90 <= lat <= 90):
                    raise ValueError(f'Invalid cached coordinates: {path}')
            cache[key] = item
        elif address[0] and not re.search(r'\bP\.?\s*O\.?\s+BOX\b', address[0], re.I):
            pending[key] = address
    if enabled:
        items = list(pending.items())
        for start in range(0, len(items), 1000):
            batch = items[start:start + 1000]
            buffer = io.StringIO(newline='')
            writer = csv.writer(buffer)
            for key, address in batch:
                writer.writerow([key, *address])
            print(f'Geocoding batch {start // 1000 + 1}: {len(batch)} addresses', flush=True)
            try:
                response = request_geocode_batch(buffer.getvalue().encode('utf-8'), benchmark,
                                                 start // 1000 + 1)
            except requests.RequestException as exc:
                print(f'Skipping unavailable Census batch {start // 1000 + 1}: {exc}', flush=True)
                continue
            returned = {}
            for values in csv.reader(io.StringIO(response.content.decode('utf-8-sig'))):
                if len(values) < 3 or values[0] not in dict(batch) or values[0] in returned:
                    raise ValueError('Unexpected geocoder CSV response; existing cache retained')
                key = values[0]
                item = {'address': dict(batch)[key], 'benchmark': benchmark,
                        'fetched_utc': datetime.now(timezone.utc).isoformat(), 'response': values,
                        'status': values[2], 'longitude': None, 'latitude': None}
                if values[2] == 'Match':
                    if len(values) < 6:
                        raise ValueError('Matched geocoder response lacks coordinates')
                    lon, lat = map(float, values[5].split(','))
                    if not (math.isfinite(lon) and math.isfinite(lat) and -180 <= lon <= 180 and -90 <= lat <= 90):
                        raise ValueError('Invalid geocoder coordinates')
                    item.update(longitude=lon, latitude=lat)
                returned[key] = item
            if set(returned) != set(dict(batch)):
                raise ValueError('Geocoder omitted requested IDs; batch not cached')
            for key, item in returned.items():
                save_json(cache_dir / f'{key}.json', item)
                cache[key] = item
    frame = frame.copy()
    frame['geocode_cache_key'] = frame.facility_id.map(address_keys)
    frame['geocode_status'] = frame.geocode_cache_key.map(lambda k: cache.get(k, {}).get('status', 'not_geocoded'))
    frame['geocode_method'] = frame.geocode_cache_key.map(
        lambda k: 'census_street_interpolation' if cache.get(k, {}).get('status') == 'Match' else None)
    frame['longitude'] = frame.geocode_cache_key.map(lambda k: cache.get(k, {}).get('longitude'))
    frame['latitude'] = frame.geocode_cache_key.map(lambda k: cache.get(k, {}).get('latitude'))
    frame['geocode_fetched_utc'] = frame.geocode_cache_key.map(lambda k: cache.get(k, {}).get('fetched_utc'))
    geometry = [Point(lon, lat) if pd.notna(lon) and pd.notna(lat) else None
                for lon, lat in zip(frame.longitude, frame.latitude)]
    frame = gpd.GeoDataFrame(frame, geometry=geometry, crs=4326)
    original_ids = frame.facility_id.copy()
    original_count = len(frame)
    frame, fallback_counts = enrich_hospital_geocodes(
        frame, cache_dir, enabled, catalog, benchmark, request_geocode_batch,
        network_fallbacks=network_fallbacks)
    if len(frame) != original_count or not frame.facility_id.equals(original_ids):
        raise ValueError('Fallback geocoding changed the facility registry identity contract')
    if quality is not None:
        quality['facility_geocoding'] = {
            'census_street_interpolation': int(frame.geocode_method.eq('census_street_interpolation').sum()),
            **fallback_counts,
            'hospitals_located': int((frame.facility_type.eq('hospital') & frame.geometry.notna()).sum()),
            'hospitals_unlocated': int((frame.facility_type.eq('hospital') & frame.geometry.isna()).sum()),
            'approximate_display_fallbacks': int(frame.fallback_longitude.notna().sum()),
        }
    return gpd.GeoDataFrame(frame, geometry='geometry', crs=4326)


def assign(frame, tracts, counties):
    frame = frame.copy()
    frame['tract_geoid'] = pd.Series(None, index=frame.index, dtype='string')
    frame['county_geoid'] = pd.Series(None, index=frame.index, dtype='string')
    frame['geography_assignment'] = 'unlocated'
    points = frame.loc[frame.geometry.notna(), ['facility_id', 'geometry']]
    for reference, key in [(tracts, 'tract_geoid'), (counties, 'county_geoid')]:
        joined = gpd.sjoin(points, reference[[key, 'geometry']], how='left', predicate='intersects')
        for idx, group in joined.groupby(level=0):
            hits = group[key].dropna().unique()
            if len(hits) == 1:
                frame.loc[idx, key] = hits[0]
            elif len(hits) > 1:
                frame.loc[idx, 'geography_assignment'] = 'ambiguous_boundary'
    valid = frame.tract_geoid.notna() & frame.county_geoid.notna()
    frame.loc[valid, 'geography_assignment'] = 'point_in_2023_polygons'
    frame.loc[frame.geometry.notna() & ~valid & (frame.geography_assignment != 'ambiguous_boundary'), 'geography_assignment'] = 'outside_reference_or_partial_match'
    return frame


def counts(base, frame, key):
    located = frame.loc[frame[key].notna()]
    all_counts = located.groupby(key).size()
    hospitals = located[located.facility_type == 'hospital']
    base = base.copy()
    base['located_registry_facility_count'] = base[key].map(all_counts).fillna(0).astype('int64')
    base['located_registry_hospital_count'] = base[key].map(hospitals.groupby(key).size()).fillna(0).astype('int64')
    base['located_hospitals_missing_beds'] = base[key].map(hospitals.groupby(key).bed_count.apply(lambda x: x.isna().sum())).fillna(0).astype('int64')
    base['located_hospital_known_beds_sum'] = base[key].map(hospitals.groupby(key).bed_count.sum(min_count=1))
    return base
