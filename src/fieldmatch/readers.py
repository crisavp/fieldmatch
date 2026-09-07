"""Observation readers: one file of any supported kind -> canonical obs cloud.

Canonical form (the ONLY thing collocation ever sees):
    dims:   obs                     (1-D, one entry per observation)
    coords: time (datetime64), lat, lon   -- all on `obs`; lon in [-180, 180]
    vars:   standardized names: hs, wind_speed, wind_dir, sig0, ... (float)

Each reader owns every format quirk of its kind (netCDF groups, `_01`/`_20`
rate suffixes, quality-flag conventions, 0-360 longitudes) so nothing
downstream needs to know the source. Readers return None when a file holds no
usable observations. Register new formats in READERS at the bottom.
"""
import warnings
from dataclasses import dataclass
from typing import Callable

import numpy as np
import xarray as xr


@dataclass(frozen=True)
class ReaderSpec:
    """One observation format: implementation, accepted options and layout."""
    reader: Callable
    options: frozenset = frozenset()
    group: str | None = None
    dim: str | tuple | None = None
    extra_groups: tuple = ()

    @property
    def layout(self):
        return {"group": self.group, "dim": self.dim,
                "extra_groups": self.extra_groups}


def _lon180(lon):
    return (lon + 180.0) % 360.0 - 180.0


def _finish(ds):
    """Common tail: normalize lon, drop obs with no time/position."""
    ds = ds.assign_coords(lon=("obs", _lon180(np.asarray(ds["lon"].values, dtype="f8"))))
    valid = (np.isfinite(ds["lat"].values) & np.isfinite(ds["lon"].values)
             & ~np.isnat(ds["time"].values) & (abs(ds["lat"].values) <= 90))
    if not valid.any():
        return None
    return ds.isel(obs=np.flatnonzero(valid))


#: Default minimum distance to the coast for altimeter retrievals, in km.
#: Altimeter waveforms are contaminated by land in the footprint and by the
#: bright-target/sigma0-bloom effects near shore; the retrieval is unreliable
#: well before the nadir point reaches land. 30 km is the common validation
#: choice. Set 0 to keep everything (the value is recorded in the output).
DEFAULT_MIN_DIST_COAST_KM = 30.0


def _flag_values_named(flag, *names):
    """Values of a CF flag variable whose flag_meanings match `names`."""
    meanings = str(flag.attrs.get("flag_meanings", "")).split()
    values = np.atleast_1d(flag.attrs.get("flag_values", np.arange(len(meanings))))
    return [int(v) for v, m in zip(values, meanings) if m in names]


def _open_sea_mask(src, dist_var, surf_var, min_dist_km, open_ocean_only,
                   open_names=("open_ocean", "ocean_or_semi_enclosed_sea")):
    """True where the retrieval is over open sea and far enough from land.

    `dist_coast` is NEGATIVE over land and positive over water (metres), so a
    single `>= threshold` test rejects land and the coastal strip together.
    Returns (mask, description) -- the description goes into the output
    attributes so the choice is auditable.
    """
    n = None
    mask = None
    notes = []
    if min_dist_km and dist_var not in src:
        notes.append(f"{dist_var} unavailable: requested distance filter not applied")
    if min_dist_km and dist_var in src:
        if src[dist_var].attrs.get("units", "m") != "m":
            raise ValueError(f"{dist_var} must be in metres; normalize units explicitly")
        d = src[dist_var].values
        n = d.size
        mask = d >= float(min_dist_km) * 1000.0
        notes.append(f"{dist_var} >= {min_dist_km:g} km")
    if open_ocean_only and surf_var not in src:
        notes.append(f"{surf_var} unavailable: requested surface filter not applied")
    if open_ocean_only and surf_var in src:
        good = _flag_values_named(src[surf_var], *open_names)
        if not good:
            notes.append(f"{surf_var} has no recognized ocean flags: surface filter not applied")
        if good:
            m2 = np.isin(src[surf_var].values, good)
            mask = m2 if mask is None else (mask & m2)
            notes.append(f"{surf_var} in {good}")
    if mask is None:
        return None, "none; " + "; ".join(notes or ["coastal/surface filters disabled"])
    return mask, " and ".join(notes)


def _open_sea_cloud(src, time, lat, lon, data_vars, dist_var, surf_var,
                    min_dist_km, open_ocean_only, provenance=None, **kw):
    """Build the canonical cloud from open-sea observations only.

    Filtering happens on the raw arrays, before the cloud is assembled, so the
    mask cannot fall out of step with rows dropped for bad geolocation.
    Dropped rather than NaN-ed: a retrieval inside the coastal strip is not a
    measurement of the open sea at all, so it should not be counted as an
    observation the model failed to match.
    """
    data_vars = dict(data_vars)
    data_vars["record_index"] = np.arange(np.asarray(time).size)
    mask, desc = _open_sea_mask(src, dist_var, surf_var, min_dist_km,
                                open_ocean_only, **kw)
    n_rejected = 0
    if mask is not None:
        idx = np.flatnonzero(mask)
        n_rejected = int(mask.size - idx.size)
        time, lat, lon = np.asarray(time)[idx], np.asarray(lat)[idx], np.asarray(lon)[idx]
        data_vars = {k: _subset_raw(v, idx) for k, v in data_vars.items()}
    prov = dict(provenance or {})
    prov.update(land_mask=desc, n_rejected_coastal=n_rejected)
    return _cloud(time, lat, lon, data_vars, provenance=prov)


#: Attributes that are COUNTS: summed when clouds from several files are
#: combined, rather than inherited from whichever file happened to be first.
COUNT_ATTRS = ("n_rejected_coastal", "n_rejected_qual", "n_read")

#: Prefix for pass-through columns requested via `extra_vars`. Keeps them in a
#: namespace of their own so a raw variable can never collide with a standard
#: name, nor accidentally trigger the direction/vector handling that
#: collocate_track keys off names like `wind_dir`.
EXTRA_PREFIX = "x_"

def _choice(option, value, allowed):
    """Validate an enumerated campaign option, failing loudly with the choices.

    Enumerated rather than free-form on purpose: these select among retrievals
    the reader knows how to handle. A free string would let the config name a
    variable the reader cannot decode (wrong rate, wrong group) and turn a
    scientific choice into a shape error.
    """
    if value not in allowed:
        raise ValueError(
            f"{option}={value!r} is not available; choose one of "
            f"{sorted(allowed)}.")
    return allowed[value]


def _unqualified(extra_vars, group):
    """Names for one group from a possibly 'group:name'-qualified list.

    `group=None` selects the unqualified names (the reader's own group);
    `group='ku'` selects those written 'ku:swh_ocean', stripped of the prefix.
    """
    if not extra_vars:
        return []
    want = [extra_vars] if isinstance(extra_vars, str) else list(extra_vars)
    out = []
    for name in want:
        head, sep, tail = name.partition(":")
        if sep and group == head:
            out.append(tail)
        elif not sep and group is None:
            out.append(name)
    return out


def _collect_extras(src, extra_vars, dim, out, prov, group_label=""):
    """Add `extra_vars` to `out` unchanged, under the EXTRA_PREFIX namespace.

    Only variables lying on the cloud's own dimension can be carried: a 20 Hz
    Sentinel-3 variable has 40 679 records against the 1 Hz track's 2 036, so
    it is a different axis, not a different preference. Refused with the axis
    named rather than silently reshaped or dropped.
    """
    if not extra_vars:
        return out, prov
    want = [extra_vars] if isinstance(extra_vars, str) else list(extra_vars)
    dims = dim if isinstance(dim, tuple) else (dim,)
    taken, missing = [], []
    for name in want:
        if name not in src.variables:
            missing.append(name)
            continue
        got = tuple(src[name].dims)
        if got != tuple(dims):
            raise ValueError(
                f"extra_vars: {name!r} lies on {got}, but this reader builds its "
                f"records on {tuple(dims)}. Variables on another axis need reader "
                f"support, not configuration -- see `fieldmatch vars`.")
        # Keep the group in the column name: Ku and C share variable names, so
        # 'ku:swh_ocean' and 'c:swh_ocean' must not collapse onto one column.
        col = f"{EXTRA_PREFIX}{group_label.replace(':', '_')}{name}"
        out[col] = src[name].load().copy(deep=True)
        taken.append(f"{group_label}{name}")
    if taken:
        prov["extra_vars"] = ", ".join(sorted(set(
            prov.get("extra_vars", "").split(", ") + taken)) ).strip(", ")
    if missing:
        # Never silently drop a requested variable: the whole point of
        # extra_vars is to stop the library hiding what a product contains.
        prov["extra_vars_missing"] = ", ".join(
            sorted(set(prov.get("extra_vars_missing", "").split(", ") + missing))
        ).strip(", ")
        warnings.warn(
            f"extra_vars: {', '.join(missing)} not present in this product "
            f"(run `fieldmatch vars` to see what is). Continuing without them.")
    return out, prov


def _subset_raw(value, idx):
    if isinstance(value, xr.DataArray):
        return np.asarray(value.values)[idx], dict(value.attrs)
    if isinstance(value, tuple) and len(value) == 2 and isinstance(value[1], dict):
        return np.asarray(value[0])[idx], value[1]
    return np.asarray(value)[idx]


def _cloud(time, lat, lon, data_vars, provenance=None):
    """Assemble the canonical obs Dataset from 1-D arrays.

    `provenance` maps attribute name -> value and is written verbatim onto the
    result: which source variable became which standard name, which filter was
    applied, what it cost. Recorded even when a filter was NOT applied, so an
    absent filter is visible rather than merely unmentioned.
    """
    from .quantities import annotate
    data_vars = dict(data_vars)
    data_vars.setdefault("record_index", np.arange(np.asarray(time).size))
    variables = {}
    for name, value in data_vars.items():
        attrs = None
        if isinstance(value, xr.DataArray):
            attrs = dict(value.attrs)
            value = value.values
        if isinstance(value, tuple) and len(value) == 2 and isinstance(value[1], dict):
            value, attrs = value
        variables[name] = annotate(xr.DataArray(np.asarray(value).ravel(), dims=("obs",), attrs=attrs), name)
    ds = xr.Dataset(
        variables,
        coords={
            "time": ("obs", np.asarray(time).ravel()),
            "lat": ("obs", np.asarray(lat, dtype="f8").ravel()),
            "lon": ("obs", np.asarray(lon, dtype="f8").ravel()),
        },
    )
    ds = _finish(ds)
    if ds is not None and provenance:
        ds.attrs.update(provenance)
    return ds


def _qc_by_flag(src, values, var_flag_pairs):
    """Apply `<flag> == 0` masking, recording per-variable what happened.

    Returns (values, provenance, n_rejected). A variable whose quality flag is
    absent from the product is recorded as unfiltered -- that is a real and
    consequential fact (S3 wind has no flag), not a detail to omit.
    """
    prov, rejected = {}, 0
    for var, flag in var_flag_pairs:
        if flag in src:
            bad = src[flag].values != 0
            rejected += int(np.count_nonzero(bad & np.isfinite(values[var])))
            values[var] = (values[var].where(~bad) if isinstance(values[var], xr.DataArray)
                           else np.where(bad, np.nan, values[var]))
            prov[f"{var}_filter"] = f"{flag} == 0"
        else:
            prov[f"{var}_filter"] = f"none ({flag} not present in this product)"
    return values, prov, rejected


# ── altimeters ─────────────────────────────────────────────────────────────
def read_altimeter_cmems(file, extra_vars=None):
    """CMEMS L3 near-real-time altimetry (global_vavh_l3_rt_*): already a flat
    along-track cloud. VAVH -> hs (filtered), WIND_SPEED -> wind_speed.

    These files carry ONLY time/lat/lon and the three geophysical variables --
    no distance-to-coast, no surface type -- so `min_dist_coast_km` cannot be
    honoured here. CMEMS edits the product upstream, but it makes no documented
    coastal-distance guarantee, so the output records `land_mask: none` rather
    than implying a filter that was never applied.
    """
    with xr.open_dataset(file) as src:
        out = {"hs": src["VAVH"],
               "hs_unfiltered": src["VAVH_UNFILTERED"],
               "wind_speed": src["WIND_SPEED"]}
        out, extra_prov = _collect_extras(src, extra_vars, "time", out, {})
        return _cloud(
            src["time"].values, src["latitude"].values, src["longitude"].values,
            out,
            provenance={**extra_prov,
                "reader": "altimeter_cmems",
                "hs_source": "VAVH", "hs_unfiltered_source": "VAVH_UNFILTERED",
                "wind_speed_source": "WIND_SPEED",
                "lat_source": "latitude", "lon_source": "longitude",
                "time_source": "time",
                "hs_filter": "none (CMEMS L3 is edited upstream)",
                "wind_speed_filter": "none (CMEMS L3 is edited upstream)",
                "land_mask": ("none (CMEMS L3 carries no dist_coast or surface "
                              "type; upstream editing only)"),
                "n_rejected_coastal": 0, "n_rejected_qual": 0,
                "n_read": int(src.sizes["time"]),
            },
        )


#: Sentinel-3 retracker choice. SAR mode is the native SRAL retrieval; PLRM
#: (pseudo-LRM) reprocesses the same echoes in a Jason-like way and is what you
#: want for strict cross-mission consistency with LRM altimeters.
S3_RETRACKERS = {"sar": "_01_ku", "plrm": "_01_plrm_ku"}


def read_altimeter_s3(file, min_dist_coast_km=DEFAULT_MIN_DIST_COAST_KM,
                      open_ocean_only=True, extra_vars=None, retracker="sar"):
    """Sentinel-3 SRAL L2 WAT (RED/STD/ENH): 1 Hz (`_01`) Ku-band ocean
    retracker. `retracker='plrm'` selects the pseudo-LRM retrieval instead.
    Quality flags applied when present (0 = good); coastal and non-open-sea
    observations dropped (see _open_sea_mask)."""
    sfx = _choice("retracker", retracker, S3_RETRACKERS)
    with xr.open_dataset(file, decode_timedelta=False) as src:
        names = {"hs": f"swh_ocean{sfx}", "wind_speed": f"wind_speed_alt{sfx}",
                 "sig0": f"sig0_ocean{sfx}"}
        missing = [v for v in names.values() if v not in src.variables]
        if missing:
            raise ValueError(
                f"retracker={retracker!r} needs {missing}, absent from this "
                f"product; try one of {sorted(S3_RETRACKERS)}.")
        out = {std: src[raw] for std, raw in names.items()}
        out, qc_prov, n_qual = _qc_by_flag(src, out, (
            ("hs", f"swh_ocean_qual{sfx}"),
            ("wind_speed", f"wind_speed_alt_qual{sfx}"),
            ("sig0", f"sig0_ocean_qual{sfx}")))
        prov = {"reader": "altimeter_s3", "retracker": retracker,
                "hs_source": f"{names['hs']} ({retracker.upper()} mode, Ku)",
                "wind_speed_source": names["wind_speed"],
                "sig0_source": names["sig0"],
                "lat_source": "lat_01", "lon_source": "lon_01",
                "time_source": "time_01",
                "rate": "1 Hz (_01)", "n_rejected_qual": n_qual,
                "n_read": int(src.sizes["time_01"]), **qc_prov}
        out, prov = _collect_extras(src, extra_vars, "time_01", out, prov)
        return _open_sea_cloud(
            src, src["time_01"].values, src["lat_01"].values,
            src["lon_01"].values, out,
            dist_var="dist_coast_01", surf_var="surf_type_01",
            min_dist_km=min_dist_coast_km, open_ocean_only=open_ocean_only,
            provenance=prov)


#: Sentinel-6 retracker: the standard MLE retrieval, or the numerical ocean
#: retracker (`_nr`). Ku only -- the C-band group ships no `_nr` variables.
S6_RETRACKERS = {"mle": "", "nr": "_nr"}
S6_BANDS = {"ku": "data_01/ku", "c": "data_01/c"}


def read_altimeter_s6(file, min_dist_coast_km=DEFAULT_MIN_DIST_COAST_KM,
                      open_ocean_only=True, extra_vars=None,
                      retracker="mle", band="ku"):
    """Sentinel-6 P4 L2 LR (RED/STD): netCDF groups. 1 Hz `data_01` for
    position/time/wind, `data_01/<band>` for swh/sig0. `retracker='nr'`
    selects the numerical ocean retracker (Ku only). Quality: *_qual == 0;
    coastal and non-open-sea observations dropped."""
    sfx = _choice("retracker", retracker, S6_RETRACKERS)
    grp = _choice("band", band, S6_BANDS)
    if sfx and band != "ku":
        raise ValueError(
            "retracker='nr' exists only for band='ku'; the C-band group ships "
            "no numerical-retracker variables.")
    with xr.open_dataset(file, group="data_01", decode_timedelta=False) as g1, \
         xr.open_dataset(file, group=grp, decode_timedelta=False) as gku:
        out = {"hs": gku[f"swh_ocean{sfx}"],
               "sig0": gku[f"sig0_ocean{sfx}"],
               "wind_speed": g1[f"wind_speed_alt{sfx}"]}
        out, qc_prov, n_qual = _qc_by_flag(gku, out, (
            ("hs", f"swh_ocean{sfx}_qual"), ("sig0", f"sig0_ocean{sfx}_qual")))
        qc_prov["wind_speed_filter"] = "none (no quality flag applied to wind_speed_alt)"
        prov = {"reader": "altimeter_s6", "retracker": retracker, "band": band,
                "hs_source": f"{grp}:swh_ocean{sfx} ({retracker.upper()})",
                "sig0_source": f"{grp}:sig0_ocean{sfx}",
                "wind_speed_source": f"data_01:wind_speed_alt{sfx}",
                "lat_source": "latitude", "lon_source": "longitude",
                "time_source": "time",
                "rate": "1 Hz (data_01)", "n_rejected_qual": n_qual,
                "n_read": int(g1.sizes["time"]), **qc_prov}
        # Ku and C share variable names, so extras may be qualified 'ku:name'
        # / 'c:name' exactly as `fieldmatch vars` displays them.
        out, prov = _collect_extras(g1, _unqualified(extra_vars, None), "time",
                                    out, prov)
        for band in ("ku", "c"):
            names = _unqualified(extra_vars, band)
            if not names:
                continue
            with xr.open_dataset(file, group=f"data_01/{band}",
                                 decode_timedelta=False) as gb:
                out, prov = _collect_extras(gb, names, "time", out, prov,
                                            group_label=f"{band}:")
        return _open_sea_cloud(
            g1, g1["time"].values, g1["latitude"].values, g1["longitude"].values,
            out,
            dist_var="distance_to_coast", surf_var="surface_classification_flag",
            min_dist_km=min_dist_coast_km, open_ocean_only=open_ocean_only,
            provenance=prov)


# ── SAR / scatterometer swaths (flattened to a cloud) ──────────────────────
def s1_good_quality_values(qflag):
    """Values of owiWindQuality / wind_quality that mean a usable retrieval.

    The convention FLIPPED between processor versions:
      IPF <= 003.xx : flag_meanings = 'good medium low poor'          -> 0 is good
      IPF >= 004.02 : flag_meanings = 'no_data bad suspect acceptable good'
                                                                      -> 0 is NO DATA
    A hardcoded `== 0` therefore keeps exactly the empty pixels and discards
    every good one on modern files (measured on a Harry scene: 3 343 kept,
    39 992 good discarded). Decide from flag_meanings instead, never from a
    hardcoded value. Shared by both pipelines -- see preprocess.py.
    """
    meanings = str(qflag.attrs.get("flag_meanings", "")).split()
    values = np.atleast_1d(qflag.attrs.get("flag_values", []))
    good = [int(v) for v, m in zip(values, meanings) if m in ("good", "acceptable")]
    if not good:
        # No usable metadata: fall back to the strictest legacy reading (0 =
        # good), which is what the archive pipeline has always done.
        warnings.warn("wind quality flag without flag_meanings; "
                      "assuming the legacy convention (0 = good)")
        good = [0]
    return good


#: Backwards-compatible private alias.
_s1_good_values = s1_good_quality_values


def read_sentinel1(file, qc=True, extra_vars=None):
    """Sentinel-1 IW OCN merged product (owi wind grid): flatten the 2-D swath
    into an obs cloud stamped with the scene time (attrs firstMeasurementTime).
    QC keeps quality in {good, acceptable} (IPF-aware) and owiMask == valid."""
    with xr.open_dataset(file) as src:
        speed = src["owiWindSpeed"].values.astype("f8")
        wdir = src["owiWindDirection"].values.astype("f8")
        if qc:
            keep = np.isin(src["owiWindQuality"].values, _s1_good_values(src["owiWindQuality"]))
            keep &= src["owiMask"].values == 0
            speed = np.where(keep, speed, np.nan)
            wdir = np.where(keep, wdir, np.nan)
        n = speed.size
        t = np.full(n, np.datetime64(src.attrs["firstMeasurementTime"].rstrip("Z")))
        out = {"wind_speed": (speed, dict(src["owiWindSpeed"].attrs)),
               "wind_dir": (wdir, dict(src["owiWindDirection"].attrs))}
        for src_name, name in (("owiEcmwfWindSpeed", "ecmwf_wind_speed"),
                               ("owiEcmwfWindDirection", "ecmwf_wind_dir")):
            if src_name in src:
                out[name] = src[src_name].values.astype("f8")
        good = s1_good_quality_values(src["owiWindQuality"]) if qc else None
        prov = {
            "reader": "sentinel1",
            "wind_speed_source": "owiWindSpeed", "wind_dir_source": "owiWindDirection",
            "lat_source": "owiLat", "lon_source": "owiLon",
            "time_source": "(global attribute firstMeasurementTime)",
            "wind_speed_filter": (f"owiWindQuality in {good} and owiMask == 0 "
                                  f"(IPF {src.attrs.get('IPFversion', '?')})"
                                  if qc else "none (qc=False)"),
            "land_mask": "owiMask == 0 (excludes land/ice/no_data/RFI)" if qc else "none",
            "n_rejected_qual": int(np.count_nonzero(np.isnan(speed))) if qc else 0,
            "n_rejected_coastal": 0, "n_read": int(speed.size),
            "note_ecmwf_columns": ("owiEcmwf* is the ECMWF first guess used INSIDE "
                                   "the CMOD inversion -- SAR wind is not independent "
                                   "of ECMWF"),
        }
        out, prov = _collect_extras(src, extra_vars,
                                    ("owiAzSize", "owiRaSize"), out, prov)
        return _cloud(t, src["owiLat"].values, src["owiLon"].values, out,
                      provenance=prov)


def read_ascat(file, extra_vars=None):
    """ASCAT L2 wind (NUMROWS x NUMCELLS): flatten to a cloud, one time per
    row. QC: wvc_quality_flag < 65536 (same rule as the legacy pipeline)."""
    with xr.open_dataset(file) as src:
        raw_time = src["time"].values
        if raw_time.ndim == 1:
            if raw_time.size != src["lat"].shape[0]:
                raise ValueError("ASCAT 1-D time must have one value per swath row")
            t2d = np.broadcast_to(raw_time[:, None], src["lat"].shape)
        else:
            if raw_time.shape != src["lat"].shape:
                raise ValueError("ASCAT time grid does not match the lat/lon swath")
            first = raw_time[:, :1]
            same = (raw_time == first) | (np.isnat(raw_time) & np.isnat(first))
            if not np.all(same):
                raise ValueError(
                    "ASCAT file has multiple timestamps within a swath row; "
                    "the campaign reader requires one time per row")
            t2d = np.broadcast_to(first, src["lat"].shape)
        good = src["wvc_quality_flag"].values < 65536
        speed = np.where(src["wvc_quality_flag"].values < 65536,
                         src["wind_speed"].values.astype("f8"), np.nan)
        wdir = np.where(src["wvc_quality_flag"].values < 65536,
                        (src["wind_dir"].values.astype("f8") + 180.0) % 360.0, np.nan)
        out = {"wind_speed": (speed, dict(src["wind_speed"].attrs)),
               "wind_dir": (wdir, {**src["wind_dir"].attrs, "direction_convention": "from_north_clockwise"})}
        prov = {
            "reader": "ascat", "wind_speed_source": "wind_speed",
            "wind_dir_source": "wind_dir (+180 degrees)",
            "lat_source": "lat", "lon_source": "lon", "time_source": "time (one per row)",
            "wind_speed_filter": "wvc_quality_flag < 65536",
            "wind_dir_filter": "wvc_quality_flag < 65536",
            "land_mask": "wvc_quality_flag < 65536",
            "n_rejected_qual": int(np.count_nonzero(~good)),
            "n_rejected_coastal": 0, "n_read": int(good.size),
        }
        out, prov = _collect_extras(src, extra_vars,
                                    ("NUMROWS", "NUMCELLS"), out, prov)
        return _cloud(t2d, src["lat"].values, src["lon"].values,
                      out, provenance=prov)


_BUOY_COLS = {  # ISPRA/RON export header -> canonical name
    "hm0": "hs", "hmax": "hmax", "mdir": "wave_dir",
    "tm01": "tm01", "tm02": "tm02", "tp": "tp",
    "la1WindSpd": "wind_speed", "la1WindDir": "wind_dir",
}


def read_buoy_ispra(file, lat=None, lon=None):
    """ISPRA/RON buoy export: semicolon CSV, header like 'hm0 [m];...', time
    'YYYY-MM-DD HH:MM:SS' UTC. Fixed-point series -> cloud with constant
    lat/lon (REQUIRED via dataset options; the export carries no position).
    Quirks: empty cells = missing; all-zero wind columns = sensor absent."""
    import csv

    if lat is None or lon is None:
        raise ValueError(
            f"buoy_ispra needs the buoy position: add `lat:` and `lon:` to the "
            f"dataset options for {file} (see the buoy map, e.g. Mappa_ROCA.pdf)")
    with open(file) as fh:
        rows = list(csv.reader(fh, delimiter=";"))
    header = [h.split(" [")[0].strip() for h in rows[0]]
    cols = {name: i for i, name in enumerate(header)}
    t = np.array([np.datetime64(r[0]) for r in rows[1:]])
    out, sources, dropped = {}, {}, []
    for src_name, name in _BUOY_COLS.items():
        if src_name not in cols:
            continue
        i = cols[src_name]
        vals = np.array([float(r[i]) if r[i].strip() else np.nan for r in rows[1:]])
        out[name] = vals
        sources[f"{name}_source"] = src_name
    # Direction 0 means north and is valid. Only a jointly all-zero speed and
    # direction pair is treated as the export's "no anemometer" sentinel.
    if "wind_speed" in out and "wind_dir" in out:
        absent = (not np.any(np.nan_to_num(out["wind_speed"]))
                  and not np.any(np.nan_to_num(out["wind_dir"])))
        if absent:
            out.pop("wind_speed")
            out.pop("wind_dir")
            sources.pop("wind_speed_source", None)
            sources.pop("wind_dir_source", None)
            dropped.extend(["la1WindSpd", "la1WindDir"])
    # Preserve explicit header units; absent units use the documented reader contract.
    for source, name in _BUOY_COLS.items():
        if name in out and " [" in rows[0][cols[source]]:
            units = rows[0][cols[source]].split(" [", 1)[1].rstrip("]")
            if units == "conv. Meteo gradi": units = "degrees"
            out[name] = (out[name], {"units": units})
    prov = {"reader": "buoy_ispra", "position": f"lat {lat}, lon {lon} (from config)",
            "time_source": header[0],
            "lat_source": "(campaign file: lat)", "lon_source": "(campaign file: lon)",
            "land_mask": "n/a (moored buoy at a fixed position)",
            "n_rejected_coastal": 0, "n_rejected_qual": 0, "n_read": int(t.size),
            **sources}
    if dropped:
        prov["dropped_all_zero_columns"] = ", ".join(dropped) + " (sensor absent)"
    return _cloud(t, np.full(t.size, float(lat)), np.full(t.size, float(lon)), out,
                  provenance=prov)


READERS = {
    "altimeter_cmems": ReaderSpec(
        read_altimeter_cmems, frozenset({"extra_vars"}), dim="time"),
    "altimeter_s3": ReaderSpec(
        read_altimeter_s3,
        frozenset({"min_dist_coast_km", "open_ocean_only", "extra_vars", "retracker"}),
        dim="time_01"),
    "altimeter_s6": ReaderSpec(
        read_altimeter_s6,
        frozenset({"min_dist_coast_km", "open_ocean_only", "extra_vars",
                   "retracker", "band"}),
        group="data_01", dim="time", extra_groups=("data_01/ku", "data_01/c")),
    "sentinel1": ReaderSpec(
        read_sentinel1, frozenset({"qc", "extra_vars"}),
        dim=("owiAzSize", "owiRaSize")),
    "ascat": ReaderSpec(
        read_ascat, frozenset({"extra_vars"}), dim=("NUMROWS", "NUMCELLS")),
    "buoy_ispra": ReaderSpec(
        read_buoy_ispra, frozenset({"lat", "lon"}), dim=None),
}


def read_obs(kind, file, **kwargs):
    """Dispatch one obs file to its reader -> canonical cloud (or None)."""
    if kind not in READERS:
        raise KeyError(f"unknown obs kind {kind!r}; known: {sorted(READERS)}")
    ds = READERS[kind].reader(file, **kwargs)
    if ds is not None:
        import hashlib
        from pathlib import Path
        h = hashlib.sha256()
        with open(file, "rb") as fh:
            for chunk in iter(lambda: fh.read(1024*1024), b""):
                h.update(chunk)
        ds["obs_id"] = ("obs", [f"{kind}:{h.hexdigest()}:{i}" for i in ds.record_index.values])
        ds["source_file"] = ("obs", np.repeat(Path(file).name, ds.sizes["obs"]))
        ds.attrs["source_sha256"] = h.hexdigest()
    return ds
