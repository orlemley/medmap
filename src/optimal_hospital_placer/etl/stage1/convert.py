"""Lossless string-valued CSV staging. No joins, geocoding, or type inference."""
import csv
import hashlib
import io
import json
from contextlib import contextmanager
from pathlib import Path
from zipfile import ZipFile

import pyarrow as pa
import pyarrow.parquet as pq

from common import normalize_headers, sha256, write_json

# Observed legacy encodings in these raw releases. Keep UTF-8 for all other
# inputs (including iQIES); caller-provided encoding overrides still take priority.
DEFAULT_ENCODINGS = {
    'CMSFacilities/FQHC_Enrollments_2026.07.17.csv': 'cp1252',
    'CMSFacilities/HHA_Enrollments_2026.07.17.csv': 'cp1252',
    'CMSFacilities/Hospice_Enrollments_2026.07.17.csv': 'cp1252',
    'CMSFacilities/Hospital_and_other.DATA.Q2_2026.csv': 'cp1252',
    'CMSFacilities/Hospital_Enrollments_2026.07.31.csv': 'cp1252',
    'CMSFacilities/RHC_Enrollments_2026.07.17.csv': 'cp1252',
    'CMSFacilities/SNF_Enrollments_2026.07.31.csv': 'cp1252',
    'RUCA/2020-rural-urban-commuting-area-codes-census-tracts.csv': 'cp1252',
}


@contextmanager
def open_text(path: Path, member: str | None, encoding: str):
    if member is None:
        with path.open('r', encoding=encoding, errors='strict', newline='') as stream:
            yield stream
    else:
        # Stream the member directly. Archive paths are never extracted to disk.
        with ZipFile(path) as archive, archive.open(member) as binary:
            with io.TextIOWrapper(binary, encoding=encoding, errors='strict', newline='') as stream:
                yield stream


def convert_csv(asset: dict, member: str | None, run: Path, encoding: str,
                batch_size: int) -> dict:
    path = Path(asset['path'])
    identity = asset['relative_path'] + ('::' + member if member else '')
    label = normalize_headers([Path(member or path.name).stem])[0][:100]
    token = hashlib.sha256(identity.encode('utf-8')).hexdigest()[:16]
    target = run / 'tables' / asset['source'] / f'{label}--{token}.parquet'
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix('.parquet.part')
    rows = 0
    try:
        with open_text(path, member, encoding) as stream:
            reader = csv.reader(stream, strict=True)
            headers = next(reader, None)
            if not headers:
                raise ValueError('CSV has no header')
            repairs = []
            trailing_hpsa_header = (
                asset['source'] == 'HPSA' and member is None
                and path.name in {'BCD_HPSA_FCT_DET_DH.csv', 'BCD_HPSA_FCT_DET_MH.csv',
                                  'BCD_HPSA_FCT_DET_PC.csv'}
                and headers[-1] == ''
            )
            if trailing_hpsa_header:
                repairs.append({'action': 'remove_empty_trailing_header',
                                'position': len(headers), 'original': '',
                                'reason': 'HRSA HPSA export header has an extra trailing delimiter'})
                headers = headers[:-1]
            names = normalize_headers(headers)
            schema = pa.schema([(name, pa.string()) for name in names], metadata={
                b'stage': b'1', b'source_identity': identity.encode('utf-8'),
                b'input_sha256': asset['sha256'].encode('ascii'),
                b'value_policy': b'all strings; blanks and sentinel values preserved',
            })
            blanks = [0] * len(names)
            columns = [[] for _ in names]
            with pq.ParquetWriter(temporary, schema, compression='zstd') as writer:
                for row in reader:
                    # Permit the corresponding empty delimiter on data rows too,
                    # but never discard a populated extra field or pad short rows.
                    if trailing_hpsa_header and len(row) == len(names) + 1 and row[-1] == '':
                        row = row[:-1]
                    if len(row) != len(names):
                        raise ValueError(f'CSV line {reader.line_num}: expected {len(names)} fields, got {len(row)}')
                    for index, value in enumerate(row):
                        columns[index].append(value)
                        blanks[index] += (value == '')
                    rows += 1
                    if len(columns[0]) >= batch_size:
                        writer.write_table(pa.Table.from_arrays([pa.array(c, type=pa.string()) for c in columns], schema=schema))
                        columns = [[] for _ in names]
                if columns[0]:
                    writer.write_table(pa.Table.from_arrays([pa.array(c, type=pa.string()) for c in columns], schema=schema))
        metadata = pq.read_metadata(temporary)
        if metadata.num_rows != rows or metadata.num_columns != len(names):
            raise ValueError('Parquet row/column counts differ from input')
        temporary.replace(target)
        result = {'source': asset['source'], 'input': identity, 'input_sha256': asset['sha256'],
                  'output': target.relative_to(run).as_posix(), 'sha256': sha256(target),
                  'rows': rows, 'columns': len(names), 'encoding': encoding, 'status': 'converted',
                  'structural_repairs': repairs,
                  'column_map': [{'position': i + 1, 'original': original, 'normalized': name,
                                  'type': 'string', 'empty_strings': blanks[i]}
                                 for i, (original, name) in enumerate(zip(headers, names))]}
        write_json(target.with_suffix('.schema.json'), result)
        return result
    except Exception:
        temporary.unlink(missing_ok=True)
        target.unlink(missing_ok=True)
        target.with_suffix('.schema.json').unlink(missing_ok=True)
        raise


def convert_assets(assets: list[dict], run: Path, encodings: dict, batch_size: int) -> tuple[list[dict], list[dict]]:
    tables, issues = [], []
    csv.field_size_limit(100_000_000)
    for asset in assets:
        if asset['status'] != 'ready':
            continue
        path = Path(asset['path'])
        members = []
        if path.suffix.lower() == '.csv':
            members = [None]
        elif path.suffix.lower() == '.zip':
            members = [m['name'] for m in asset['members'] if m['name'].lower().endswith('.csv')]
            if len(members) != len(set(members)):
                issues.append({'input': asset['relative_path'], 'error': 'Duplicate CSV member names in ZIP'})
                asset['status'] = 'failed'
                continue
        if not members:
            asset['stage1_action'] = 'reference_only'
            continue
        asset['stage1_action'] = 'convert_csv'
        for member in members:
            identity = asset['relative_path'] + ('::' + member if member else '')
            encoding = encodings.get(identity, encodings.get(asset['source'],
                                    DEFAULT_ENCODINGS.get(identity, 'utf-8-sig')))
            print(f'Converting {identity}', flush=True)
            try:
                tables.append(convert_csv(asset, member, run, encoding, batch_size))
            except Exception as exc:
                issues.append({'input': identity, 'error': str(exc), 'encoding': encoding})
        write_json(run / 'tables.json', tables)
        write_json(run / 'issues.json', issues)
    return tables, issues
