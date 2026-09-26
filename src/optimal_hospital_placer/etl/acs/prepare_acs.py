"""Prepare ACS estimates/MOEs without modifying stages 1, 2, or 3."""
import csv
import re

import pandas as pd

from acs_common import (YEAR, TABLES, SHELL, GEOGRAPHY, PREPARED, code_hash, complete,
                        fingerprint, read, reusable, save, validate_raw)

# Preserve special values explicitly rather than interpreting them as counts.
# Thresholded, unavailable, and controlled-estimate values remain null here.
SPECIAL = {'', '.', '-', '**', '***', '*****', 'N', '(X)', 'null',
           '-222222222', '-333333333', '-555555555', '-666666666',
           '-888888888', '-999999999'}
GEO_PATTERN = r'(?:1400000US[0-9]{11}|0500000US[0-9]{5})'


def subset(path):
    pieces = []
    for chunk in pd.read_csv(path, sep='|', dtype='string', keep_default_na=False,
                             encoding='utf-8-sig', chunksize=10000):
        if 'GEO_ID' not in chunk:
            raise ValueError(f'Missing GEO_ID in {path}')
        part = chunk.loc[chunk.GEO_ID.str.fullmatch(GEO_PATTERN)].copy()
        if not part.empty:
            pieces.append(part)
    if not pieces:
        raise ValueError(f'No tract/county records in {path}')
    result = pd.concat(pieces, ignore_index=True)
    if result.GEO_ID.duplicated().any():
        raise ValueError(f'Duplicate GEO_ID in {path}')
    return result


def prepare():
    shell_path, shell_hash = validate_raw(SHELL)
    geo_path, geo_hash = validate_raw(GEOGRAPHY)
    with shell_path.open(encoding='utf-8-sig', newline='') as stream:
        shells = {r['Unique ID']: r for r in csv.DictReader(stream, delimiter='|')
                  if r['Table ID'] in TABLES and re.fullmatch(r'[BC][0-9]{5}[A-Z]*_[0-9]{3}', r['Unique ID'])}
    # Preserve the hierarchical labels (e.g. Male > Under 5 years), not just
    # ambiguous leaf labels repeated under multiple categories.
    stacks = {}
    for row in shells.values():
        stack = stacks.setdefault(row['Table ID'], {})
        depth = int(float(row['Indent']))
        for level in list(stack):
            if level >= depth:
                del stack[level]
        stack[depth] = row['Label']
        row['Label path'] = ' > '.join(stack[level] for level in sorted(stack))
    geos = subset(geo_path).set_index('GEO_ID')
    if not {'NAME', 'STATE', 'COUNTY', 'TRACT'} <= set(geos.columns):
        raise ValueError('ACS geography schema changed')
    component_id = geos.STATE + geos.COUNTY + geos.TRACT
    county = geos.index.str.startswith('050')
    component_id.loc[county] = (geos.STATE + geos.COUNTY).loc[county]
    if not component_id.eq(geos.index.str.split('US').str[-1]).all():
        raise ValueError('ACS geography components disagree with GEO_ID')
    prepared = []
    for table in TABLES:
        path, digest = validate_raw(f'acsdt5y{YEAR}-{table.lower()}.dat')
        identity = {'table': table, 'raw': digest, 'shell': shell_hash, 'geography': geo_hash,
                    'code': code_hash('prepare_acs.py')}
        dest = PREPARED / 'tables' / table / fingerprint(identity)
        if reusable(dest, identity):
            print(f'Using prepared {table}', flush=True)
        else:
            print(f'Preparing {table}', flush=True)
            dest.mkdir(parents=True, exist_ok=True)
            save(dest / 'manifest.json', {'status': 'running', 'identity': identity})
            try:
                data = subset(path).set_index('GEO_ID')
                if not data.index.isin(geos.index).all():
                    raise ValueError(f'{table}: IDs absent from geography file')
                dictionary, issues = {}, []
                numeric = pd.DataFrame(index=data.index)
                for column in data:
                    match = re.fullmatch(rf'{table}_([EM])([0-9]{{3}})', column)
                    if not match:
                        raise ValueError(f'Unexpected ACS data column: {column}')
                    kind, line = match.groups()
                    shell = shells[f'{table}_{line}']
                    partner = f'{table}_{"M" if kind == "E" else "E"}{line}'
                    if partner not in data:
                        raise ValueError(f'Missing estimate/MOE partner: {partner}')
                    raw = data[column].str.strip()
                    special = raw.isin(SPECIAL) | raw.str.fullmatch(r'[0-9,]+[+-]')
                    values = pd.to_numeric(raw.mask(special), errors='coerce').astype('Float64')
                    bad = ~special & (values.isna() | values.lt(0).fillna(False)
                                      | values.isin([float('inf'), float('-inf')]))
                    if bad.any():
                        raise ValueError(f'{column}: unexpected values {raw.loc[bad].unique()[:5].tolist()}')
                    name = 'acs_' + column.lower()
                    numeric[name] = values
                    # Raw special tokens are kept per cell for later interpretation.
                    numeric[name + '_annotation'] = raw.where(special & raw.ne(''), pd.NA)
                    counts = raw.loc[special].value_counts().to_dict()
                    if counts:
                        issues.append({'column': column, 'special_value_counts': {k: int(v) for k, v in counts.items()}})
                    dictionary[name] = {'source_variable': column, 'table': table,
                         'label': shell['Label'], 'label_path': shell['Label path'],
                         'title': shell['Title'], 'universe': shell['Universe'],
                         'kind': 'estimate' if kind == 'E' else 'margin_of_error',
                         'survey_period': [YEAR - 4, YEAR], 'source_type': shell['Type'],
                         'annotation_column': name + '_annotation'}
                numeric.to_parquet(dest / 'table.parquet', index=True, compression='zstd')
                save(dest / 'dictionary.json', dictionary)
                save(dest / 'issues.json', issues)
                complete(dest, identity, ['table.parquet', 'dictionary.json', 'issues.json'])
            except Exception as exc:
                save(dest / 'manifest.json', {'status': 'failed', 'identity': identity, 'error': str(exc)})
                raise
        prepared.append(dest)
    identity = {'tables': {d.parent.name: read(d / 'manifest.json') for d in prepared},
                'geography': geo_hash, 'code': code_hash('prepare_acs.py')}
    run = PREPARED / 'runs' / fingerprint(identity)
    if not reusable(run, identity):
        run.mkdir(parents=True, exist_ok=True)
        frame = geos[['NAME']].rename(columns={'NAME': 'acs_geography_name'})
        dictionary, issues = {}, {}
        for dest in prepared:
            part = pd.read_parquet(dest / 'table.parquet')
            frame = frame.join(part, how='left', validate='one_to_one')
            frame[f'acs_{dest.parent.name.lower()}_record_present'] = frame.index.isin(part.index)
            dictionary.update(read(dest / 'dictionary.json'))
            issues[dest.parent.name] = read(dest / 'issues.json')
        for name, prefix, key in [('tracts', '1400000US', 'tract_geoid'), ('counties', '0500000US', 'county_geoid')]:
            selected = frame.loc[frame.index.str.startswith(prefix)].copy()
            selected[key] = selected.index.str[len(prefix):]
            selected['acs_release_year'] = YEAR
            selected['acs_period_start'] = YEAR - 4
            selected['acs_period_end'] = YEAR
            selected.reset_index().rename(columns={'GEO_ID': 'acs_geo_id'}).to_parquet(
                run / f'acs_{name}.parquet', index=False, compression='zstd')
        save(run / 'data_dictionary.json', dictionary)
        save(run / 'issues.json', issues)
        complete(run, identity, ['acs_tracts.parquet', 'acs_counties.parquet', 'data_dictionary.json', 'issues.json'], year=YEAR)
    else:
        print('Using completed ACS preparation snapshot', flush=True)
    save(PREPARED / 'latest_success.json', {'run_directory': str(run)})
    return run


if __name__ == '__main__':
    print(prepare())
