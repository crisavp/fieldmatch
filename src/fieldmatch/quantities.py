"""Small, shared table of physical meanings. Extend here, not in CLI branches.

Names identify quantities, not just units: Hmax is not Hs; Tm01 is not Te;
wave-model neutral wind is not atmospheric 10 m wind. No implicit conversions.
"""
QUANTITIES = {
    'hs': ('m', 'scalar'), 'hmax': ('m', 'scalar'),
    'tp': ('s', 'scalar'), 'tm01': ('s', 'scalar'), 'tm02': ('s', 'scalar'),
    'energy_period': ('s', 'scalar'), 'wave_dir': ('degrees', 'circular'),
    'wind_speed': ('m s-1', 'scalar'), 'wind_dir': ('degrees', 'circular'),
    'neutral_wind_speed': ('m s-1', 'scalar'), 'neutral_wind_dir': ('degrees', 'circular'),
    'u10': ('m s-1', 'scalar'), 'v10': ('m s-1', 'scalar'),
}
ALIASES = {'swh': 'hs', 'mwd': 'wave_dir', 'mdir': 'wave_dir', 'pp1d': 'tp',
           'mwp': 'energy_period', 'wind': 'neutral_wind_speed', 'dwi': 'neutral_wind_dir'}
PARAMETERS = {140229: 'hs', 140230: 'wave_dir', 140231: 'tp', 140232: 'energy_period',
              140245: 'neutral_wind_speed', 140249: 'neutral_wind_dir', 165: 'u10', 166: 'v10'}
DIRECTION_VARS = {k for k, (_, kind) in QUANTITIES.items() if kind == 'circular'}
DIRECTION_VARS |= {k for k, v in ALIASES.items() if v in DIRECTION_VARS}


def definition(name):
    return ALIASES.get(name, name)


def unit_name(value):
    return {'m/s': 'm s-1', 'm s**-1': 'm s-1', 'm s^-1': 'm s-1',
            'Degree true': 'degrees', 'degree': 'degrees', 'degrees_true': 'degrees', 'degree_true': 'degrees'}.get(value, value)


def annotate(arr, source_name):
    """Preserve provider attributes, supplement known canonical reader/GRIB contracts."""
    arr = arr.copy(deep=False)
    arr.attrs = dict(arr.attrs)
    q = PARAMETERS.get(arr.attrs.get('GRIB_paramId'), definition(source_name))
    if q in QUANTITIES:
        arr.attrs.setdefault('quantity', q)
        if 'units' not in arr.attrs:
            arr.attrs.update(units=QUANTITIES[q][0], units_source='FieldMatch quantity contract')
        if QUANTITIES[q][1] == 'circular':
            arr.attrs.setdefault('direction_convention', 'from_north_clockwise')
    return arr


def validate(arr, variable):
    arr = annotate(arr, arr.name or variable)
    expected = definition(variable)
    actual = arr.attrs.get('quantity', definition(arr.name or variable))
    if actual != expected:
        raise ValueError(f'incompatible quantities: {actual} cannot be compared as {expected}')
    if expected in QUANTITIES:
        units, kind = QUANTITIES[expected]
        if unit_name(arr.attrs.get('units')) != units:
            raise ValueError(f'incompatible units for {variable}: {arr.attrs.get("units")!r}; expected {units}')
        if kind == 'circular' and arr.attrs.get('direction_convention') != 'from_north_clockwise':
            raise ValueError(f'incompatible direction convention for {variable}; normalize explicitly')
    return arr
