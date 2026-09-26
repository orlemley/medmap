"""Explicit, conservative source interpretation; no geographic transformations."""
import re

VERSION = 2
TYPES = {'string', 'int64', 'float64', 'bool', 'date', 'interval'}


def numeric(kind='float64', minimum=None, maximum=None, missing=None, unit=None):
    return {'type': kind, 'minimum': minimum, 'maximum': maximum,
            'missing': missing or [], 'unit': unit, 'measurement_year': None}


def builtin(source, name):
    """Unlisted fields are retained as text, never inferred from sampled values."""
    if source == 'SVI':
        if re.match(r'^(e|m|ep|mp|epl|rpl|spl|f)_', name) or name == 'area_sqmi':
            kind = 'int64' if re.match(r'^(e|m|f)_', name) else 'float64'
            maximum = 1 if name.startswith(('epl_', 'rpl_')) else None
            unit = 'percentile' if maximum == 1 else ('percent' if name.startswith(('ep_', 'mp_')) else None)
            rule = numeric(kind, 0, maximum, ['-999', '-999.0'], unit)
            if name.startswith(('m_', 'mp_')):
                # Census controlled-estimate MOE annotation, not a negative MOE.
                rule['missing_reasons'] = {token: 'controlled_estimate_moe'
                                           for token in ('-555555555', '-555555555.0', '-555555555.00')}
            return rule
    if source == 'PLACES':
        if name.endswith(('_crudeprev', '_adjprev')):
            return numeric(minimum=0, maximum=100, unit='percent')
        if name.endswith(('_crude95ci', '_adj95ci')):
            return numeric('interval', 0, 100, unit='percent')
        if name in {'totalpopulation', 'totalpop18plus'}:
            return numeric('int64', 0, unit='people')
    if source == 'CMSHospital':
        missing = ['Not Available', 'Not Applicable']
        if name in {'emergency_services', 'meets_criteria_for_birthing_friendly_designation'}:
            return {'type': 'bool', 'missing': missing}
        if name == 'hospital_overall_rating':
            return numeric('int64', 1, 5, missing, 'stars')
        if name.endswith('_measure_count') or name.startswith('count_of_facility_'):
            return numeric('int64', 0, missing=missing, unit='count')
    if source == 'CMSFacilities':
        if name in {'bed_cnt', 'crtfd_bed_cnt',
                    'mdcr_snf_bed_cnt', 'mdcd_nf_bed_cnt', 'mdcr_mdcd_snf_bed_cnt'}:
            return numeric('int64', 0, missing=['Not Applicable', 'Not Available'], unit='beds')
    if source == 'HPSA':
        if name in {'hpsa_score', 'pc_mcta_score'}:
            return numeric('int64', 0, missing=['NA'])
        if name in {'hpsa_fte', 'hpsa_designation_population', 'hpsa_estimated_served_population',
                    'hpsa_estimated_underserved_population', 'hpsa_resident_civilian_population',
                    'hpsa_shortage'}:
            # Preserve negative published estimates; do not assume they are sentinels.
            return numeric()
        if name == 'of_population_below_100_poverty':
            rule = numeric(minimum=0, maximum=100, unit='percent')
            # A few published values exceed 100. Retain the original in row-level
            # quality flags, publish null for the unusable percentage, and warn.
            rule['on_invalid'] = 'null_with_warning'
            return rule
        if name in {'hpsa_designation_date', 'hpsa_designation_last_update_date', 'withdrawn_date',
                    'hpsa_withdrawn_date_string'}:
            return {'type': 'date', 'missing': []}
    if source == 'MUAP':
        if name == 'imu_score':
            return numeric(minimum=0, maximum=100)
        if name in {'designation_date', 'mua_p_designation_date_string', 'mua_p_update_date',
                    'mua_p_update_date_string', 'medically_underserved_area_population_mua_p_withdrawal_date'}:
            return {'type': 'date', 'missing': []}
        if name in {'percentage_of_population_age_65_and_over',
                    'percent_of_population_with_incomes_at_or_below_100_percent_of_the_u_s_federal_poverty_level'}:
            return numeric(minimum=0, maximum=100, unit='percent')
    if source == 'RUCA':
        if name == 'population':
            return numeric('int64', 0, unit='people')
        if name in {'landarea', 'popdensity'}:
            return numeric(minimum=0)
        # RUCA classifications, destinations and both FIPS vintages stay as strings.
    return {'type': 'string', 'missing': [], 'review_required': True}


def rule_for(source, column, identity, overrides):
    rule = builtin(source, column)
    origin = 'builtin' if rule['type'] != 'string' else 'unreviewed_text'
    for scope, key in [('sources', source), ('tables', identity)]:
        custom = overrides.get(scope, {}).get(key, {}).get(column)
        if custom is not None:
            rule = {**rule, **custom}
            origin = 'configured'
    if rule['type'] not in TYPES:
        raise ValueError(f'Unknown type for {column}: {rule["type"]}')
    if not isinstance(rule.get('missing', []), list) or not all(isinstance(v, str) for v in rule.get('missing', [])):
        raise ValueError(f'Missing tokens must be strings for {column}')
    rule['origin'] = origin
    rule['review_required'] = origin == 'unreviewed_text'
    return rule
