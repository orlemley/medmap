"""Batch transforms with per-column audits; no joins or dropped rows."""
import hashlib
import json
import math
import re
from collections import Counter
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from stage2_rules import rule_for


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
    temporary.replace(path)


def arrow_type(kind):
    return {'string': pa.string(), 'int64': pa.int64(), 'float64': pa.float64(),
            'bool': pa.bool_(), 'date': pa.date32(),
            'interval': pa.struct([('lower', pa.float64()), ('upper', pa.float64())])}[kind]


def parse(value, rule):
    if value is None or not value.strip():
        return None, 'blank'
    text = value.strip()
    if text in rule.get('missing_reasons', {}):
        return None, rule['missing_reasons'][text]
    if text.casefold() in {item.casefold() for item in rule.get('missing', [])}:
        return None, 'sentinel'
    kind = rule['type']
    if kind == 'string':
        # Preserve unknown codes, identifiers, addresses and original whitespace.
        return value, None
    if kind == 'bool':
        if text.lower() not in {'yes', 'no', 'y', 'n'}:
            raise ValueError('Expected Yes/No or Y/N')
        return text.lower() in {'yes', 'y'}, None
    if kind == 'date':
        for fmt in ('%m/%d/%Y', '%Y/%m/%d', '%Y-%m-%d', '%Y-%m-%dT%H:%M:%S', '%m/%d/%Y %H:%M:%S'):
            try:
                return datetime.strptime(text, fmt).date(), None
            except ValueError:
                pass
        raise ValueError('Unrecognized date format')
    if kind == 'interval':
        match = re.fullmatch(r'\(?\s*(\d+(?:\.\d+)?)\s*,\s*(\d+(?:\.\d+)?)\s*\)?', text)
        if not match:
            raise ValueError('Expected confidence interval: (lower, upper)')
        lower, upper = map(float, match.groups())
        if not 0 <= lower <= upper <= 100:
            raise ValueError('Confidence interval must satisfy 0 <= lower <= upper <= 100')
        return {'lower': lower, 'upper': upper}, None
    try:
        number = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError('Invalid numeric value') from exc
    if not number.is_finite():
        raise ValueError('Non-finite number')
    if kind == 'int64':
        if number != number.to_integral_value() or not -(2**63) <= number < 2**63:
            raise ValueError('Value is not an int64')
        result = int(number)
    else:
        result = float(number)
        if not math.isfinite(result):
            raise ValueError('Float overflow')
    if rule.get('minimum') is not None and result < rule['minimum']:
        raise ValueError('Below configured minimum')
    if rule.get('maximum') is not None and result > rule['maximum']:
        raise ValueError('Above configured maximum')
    return result, None


def transform(entry, stage1, run, overrides, batch_size):
    path = (stage1 / entry['output']).resolve()
    if stage1 not in path.parents:
        raise ValueError('Input table path escapes the stage 1 run')
    expected = entry['sha256'].lower()
    if digest(path) != expected:
        raise ValueError('Stage 1 Parquet checksum mismatch')
    parquet = pq.ParquetFile(path)
    if parquet.metadata.num_rows != entry['rows']:
        raise ValueError('Stage 1 row count differs from manifest')
    names = parquet.schema_arrow.names
    if len(set(names)) != len(names) or any(name.startswith('_stage2_') for name in names):
        raise ValueError('Duplicate or reserved input column name')
    if not all(pa.types.is_string(field.type) for field in parquet.schema_arrow):
        raise ValueError('Stage 2 expects string-valued stage 1 columns')
    rules = {name: rule_for(entry['source'], name, entry['input'], overrides) for name in names}
    fields = [(name, arrow_type(rules[name]['type'])) for name in names]
    fields += [('_stage2_source_row', pa.int64()), ('_stage2_source_table', pa.string()),
               ('_stage2_quality_flags', pa.string())]
    schema = pa.schema(fields, metadata={b'stage': b'2', b'input_sha256': expected.encode(),
                                      b'geography_aligned': b'false'})
    # Output name is based on source identity, not a source-controlled filesystem path.
    token = hashlib.sha256(entry['input'].encode()).hexdigest()[:20]
    target = run / 'tables' / f'{token}.parquet'
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix('.parquet.part')
    counts = {name: Counter() for name in names}
    samples, warning_samples, errors, warnings, row_count = [], [], 0, 0, 0
    try:
        with pq.ParquetWriter(temporary, schema, compression='zstd') as writer:
            for batch in parquet.iter_batches(batch_size=batch_size):
                arrays = []
                row_flags = [[] for _ in range(batch.num_rows)]
                for name, column in zip(names, batch.columns):
                    converted = []
                    for offset, raw in enumerate(column.to_pylist(), 1):
                        try:
                            value, reason = parse(raw, rules[name])
                            counts[name][reason or 'present'] += 1
                            if reason not in {None, 'blank', 'sentinel'}:
                                row_flags[offset - 1].append({'column': name, 'raw_value': raw, 'reason': reason})
                        except (ValueError, TypeError, OverflowError) as exc:
                            value = None
                            detail = {'row': row_count + offset, 'column': name,
                                      'value': raw, 'error': str(exc)}
                            if rules[name].get('on_invalid') == 'null_with_warning':
                                warnings += 1
                                counts[name]['invalid_warned'] += 1
                                row_flags[offset - 1].append({'column': name, 'raw_value': raw,
                                                             'reason': 'invalid_value', 'error': str(exc)})
                                if len(warning_samples) < 100:
                                    warning_samples.append(detail)
                            else:
                                errors += 1
                                counts[name]['invalid'] += 1
                                if len(samples) < 100:
                                    samples.append(detail)
                        converted.append(value)
                    arrays.append(pa.array(converted, type=arrow_type(rules[name]['type'])))
                arrays.append(pa.array(range(row_count + 1, row_count + batch.num_rows + 1), type=pa.int64()))
                arrays.append(pa.array([entry['input']] * batch.num_rows, type=pa.string()))
                arrays.append(pa.array([json.dumps(flags, ensure_ascii=False) if flags else None
                                        for flags in row_flags], type=pa.string()))
                writer.write_table(pa.Table.from_arrays(arrays, schema=schema))
                row_count += batch.num_rows
        report = {'input': entry['input'], 'source': entry['source'], 'rows': row_count,
                  'invalid_cells': errors, 'error_samples': samples,
                  'warning_cells': warnings, 'warning_samples': warning_samples,
                  'column_rules': rules, 'column_counts': {k: dict(v) for k, v in counts.items()},
                  'review_required': [name for name in names if rules[name]['review_required']],
                  'stage1_column_map': entry.get('column_map', []),
                  'measurement_year_policy': 'Unknown unless explicitly configured; never inferred from filename'}
        save(run / 'reports' / f'{token}.json', report)
        if errors:
            raise ValueError(f'{errors} invalid cells; see reports/{token}.json. No table published.')
        if row_count != entry['rows'] or pq.read_metadata(temporary).num_rows != row_count:
            raise ValueError('Row conservation check failed')
        if digest(path) != expected:
            raise ValueError('Stage 1 table changed during processing')
        temporary.replace(target)
        return {'source': entry['source'], 'input': entry['input'], 'stage1_output': entry['output'],
                'input_sha256': expected, 'output': target.relative_to(run).as_posix(),
                'sha256': digest(target), 'rows': row_count, 'columns': len(schema),
                'report': f'reports/{token}.json', 'warning_cells': warnings,
                'review_required_columns': len(report['review_required'])}
    except Exception:
        temporary.unlink(missing_ok=True)
        target.unlink(missing_ok=True)
        raise
