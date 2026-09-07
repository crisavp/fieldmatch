"""Shared spatial sampling for point and grid comparisons; no extrapolation."""
import numpy as np
from .quantities import DIRECTION_VARS, definition


def _spatial(lat, lon, field, points, method):
    """No extrapolation. Missing values matter only at nonzero-weight corners."""
    y, x = points.T
    j = np.clip(np.searchsorted(lat, y)-1, 0, len(lat)-2)
    k = np.clip(np.searchsorted(lon, x)-1, 0, len(lon)-2)
    fy = (y-lat[j])/(lat[j+1]-lat[j]); fx = (x-lon[k])/(lon[k+1]-lon[k])
    if method == "nearest":
        out = field[j+(fy > .5), k+(fx > .5)].astype(float)
    else:
        out = np.zeros(len(points))
        for dj, dk, weight in ((0,0,(1-fy)*(1-fx)), (0,1,(1-fy)*fx),
                               (1,0,fy*(1-fx)), (1,1,fy*fx)):
            term = np.zeros(len(points))
            np.multiply(field[j+dj,k+dk], weight, out=term, where=weight != 0)
            out += term
    outside = (y<lat[0]) | (y>lat[-1]) | (x<lon[0]) | (x>lon[-1])
    return np.where(outside, np.nan, out)



def sample_quantity(fields, variable, lat, lon, points, method,
                    direction_resultant_min=1e-10, wind_direction_min_speed=1e-10):
    """Sample validated scalar, circular or u/v fields using one spatial policy."""
    def sample(a):
        return _spatial(lat, lon, a, points, method)
    if set(fields) == {'u10', 'v10'}:
        u, v = sample(fields['u10']), sample(fields['v10'])
        speed = np.hypot(u, v)
        return speed if variable == 'wind_speed' else np.where(
            speed > wind_direction_min_speed,
            (270. - np.degrees(np.arctan2(v, u))) % 360., np.nan)
    field = next(iter(fields.values()))
    if definition(variable) in DIRECTION_VARS:
        angle = np.deg2rad(field)
        sn, cs = sample(np.sin(angle)), sample(np.cos(angle))
        return np.where(np.hypot(sn, cs) > direction_resultant_min,
                        np.degrees(np.arctan2(sn, cs)) % 360., np.nan)
    return sample(field)
