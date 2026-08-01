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

import numpy as np
import xarray as xr


def _lon180(lon):
    return (lon + 180.0) % 360.0 - 180.0


def _finish(ds):
    """Common tail: normalize lon, drop obs with no time/position."""
    ds = ds.assign_coords(lon=("obs", _lon180(np.asarray(ds["lon"].values, dtype="f8"))))
    valid = (np.isfinite(ds["lat"].values) & np.isfinite(ds["lon"].values)
             & ~np.isnat(ds["time"].values))
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
    if min_dist_km and dist_var in src:
        d = src[dist_var].values
        n = d.size
        mask = d >= float(min_dist_km) * 1000.0
        notes.append(f"{dist_var} >= {min_dist_km:g} km")
    if open_ocean_only and surf_var in src:
        good = _flag_values_named(src[surf_var], *open_names)
        if good:
            m2 = np.isin(src[surf_var].values, good)
            mask = m2 if mask is None else (mask & m2)
            notes.append(f"{surf_var} in {good}")
    if mask is None:
        return None, "none (product has no coastal/surface-type variables)"
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
    mask, desc = _open_sea_mask(src, dist_var, surf_var, min_dist_km,
                                open_ocean_only, **kw)
    n_rejected = 0
    if mask is not None:
        idx = np.flatnonzero(mask)
        n_rejected = int(mask.size - idx.size)
        time, lat, lon = np.asarray(time)[idx], np.asarray(lat)[idx], np.asarray(lon)[idx]
        data_vars = {k: np.asarray(v)[idx] for k, v in data_vars.items()}
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

#: Where each obs kind's cloud is built from: the netCDF group holding the
#: geolocation, and the dimension its records lie on. `varlist` uses this to
#: show the user exactly the variables that `extra_vars` can accept, so the
#: lister and the readers cannot drift apart.
#:   group: netCDF group to open (None = root)
#:   dim:   dimension the canonical cloud is indexed by
#:   extra_groups: further groups whose variables share that dimension
LAYOUT = {
    "altimeter_cmems": {"group": None, "dim": "time", "extra_groups": ()},
    "altimeter_s3": {"group": None, "dim": "time_01", "extra_groups": ()},
    "altimeter_s6": {"group": "data_01", "dim": "time",
                     "extra_groups": ("data_01/ku", "data_01/c")},
    "sentinel1": {"group": None, "dim": ("owiAzSize", "owiRaSize"), "extra_groups": ()},
    "ascat": {"group": None, "dim": ("NUMROWS", "NUMCELLS"), "extra_groups": ()},
    "buoy_ispra": {"group": None, "dim": None, "extra_groups": ()},   # CSV
}


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
                f"support, not configuration -- see `matchup vars`.")
        # Keep the group in the column name: Ku and C share variable names, so
        # 'ku:swh_ocean' and 'c:swh_ocean' must not collapse onto one column.
        col = f"{EXTRA_PREFIX}{group_label.replace(':', '_')}{name}"
        out[col] = src[name].values
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
            f"(run `matchup vars` to see what is). Continuing without them.")
    return out, prov


def _cloud(time, lat, lon, data_vars, provenance=None):
    """Assemble the canonical obs Dataset from 1-D arrays.

    `provenance` maps attribute name -> value and is written verbatim onto the
    result: which source variable became which standard name, which filter was
    applied, what it cost. Recorded even when a filter was NOT applied, so an
    absent filter is visible rather than merely unmentioned.
    """
    ds = xr.Dataset(
        {k: ("obs", np.asarray(v, dtype="f8").ravel()) for k, v in data_vars.items()},
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
            values[var] = np.where(bad, np.nan, values[var])
            prov[f"{var}_filter"] = f"{flag} == 0"
        else:
            prov[f"{var}_filter"] = f"none ({flag} not present in this product)"
    return values, prov, rejected


# ── altimeters ─────────────────────────────────────────────────────────────
def read_altimeter_cmems(file, extra_vars=None, **_):
    """CMEMS L3 near-real-time altimetry (global_vavh_l3_rt_*): already a flat
    along-track cloud. VAVH -> hs (filtered), WIND_SPEED -> wind_speed.

    These files carry ONLY time/lat/lon and the three geophysical variables --
    no distance-to-coast, no surface type -- so `min_dist_coast_km` cannot be
    honoured here. CMEMS edits the product upstream, but it makes no documented
    coastal-distance guarantee, so the output records `land_mask: none` rather
    than implying a filter that was never applied.
    """
    with xr.open_dataset(file) as src:
        out = {"hs": src["VAVH"].values,
               "hs_unfiltered": src["VAVH_UNFILTERED"].values,
               "wind_speed": src["WIND_SPEED"].values}
        out, extra_prov = _collect_extras(src, extra_vars, "time", out, {})
        return _cloud(
            src["time"].values, src["latitude"].values, src["longitude"].values,
            out,
            provenance={**extra_prov,
                "reader": "altimeter_cmems",
                "hs_source": "VAVH", "hs_unfiltered_source": "VAVH_UNFILTERED",
                "wind_speed_source": "WIND_SPEED",
                "hs_filter": "none (CMEMS L3 is edited upstream)",
                "wind_speed_filter": "none (CMEMS L3 is edited upstream)",
                "land_mask": ("none (CMEMS L3 carries no dist_coast or surface "
                              "type; upstream editing only)"),
                "n_rejected_coastal": 0, "n_rejected_qual": 0,
                "n_read": int(src.sizes["time"]),
            },
        )


def read_altimeter_s3(file, min_dist_coast_km=DEFAULT_MIN_DIST_COAST_KM,
                      open_ocean_only=True, extra_vars=None, **_):
    """Sentinel-3 SRAL L2 WAT (RED/STD/ENH): use the 1 Hz (`_01`) Ku-band
    ocean retracker. Quality flags applied when present (0 = good); coastal
    and non-open-sea observations dropped (see _open_sea_mask)."""
    with xr.open_dataset(file, decode_timedelta=False) as src:
        out = {"hs": src["swh_ocean_01_ku"].values,
               "wind_speed": src["wind_speed_alt_01_ku"].values,
               "sig0": src["sig0_ocean_01_ku"].values}
        out, qc_prov, n_qual = _qc_by_flag(src, out, (
            ("hs", "swh_ocean_qual_01_ku"),
            ("wind_speed", "wind_speed_alt_qual_01_ku"),
            ("sig0", "sig0_ocean_qual_01_ku")))
        prov = {"reader": "altimeter_s3",
                "hs_source": "swh_ocean_01_ku (SAR mode, Ku; not _plrm_)",
                "wind_speed_source": "wind_speed_alt_01_ku",
                "sig0_source": "sig0_ocean_01_ku",
                "rate": "1 Hz (_01)", "n_rejected_qual": n_qual,
                "n_read": int(src.sizes["time_01"]), **qc_prov}
        out, prov = _collect_extras(src, extra_vars, "time_01", out, prov)
        return _open_sea_cloud(
            src, src["time_01"].values, src["lat_01"].values,
            src["lon_01"].values, out,
            dist_var="dist_coast_01", surf_var="surf_type_01",
            min_dist_km=min_dist_coast_km, open_ocean_only=open_ocean_only,
            provenance=prov)


def read_altimeter_s6(file, min_dist_coast_km=DEFAULT_MIN_DIST_COAST_KM,
                      open_ocean_only=True, extra_vars=None, **_):
    """Sentinel-6 P4 L2 LR (RED/STD): netCDF groups. 1 Hz `data_01` for
    position/time/wind, `data_01/ku` for swh/sig0. Quality: *_qual == 0;
    coastal and non-open-sea observations dropped."""
    with xr.open_dataset(file, group="data_01", decode_timedelta=False) as g1, \
         xr.open_dataset(file, group="data_01/ku", decode_timedelta=False) as gku:
        out = {"hs": gku["swh_ocean"].values, "sig0": gku["sig0_ocean"].values,
               "wind_speed": g1["wind_speed_alt"].values}
        out, qc_prov, n_qual = _qc_by_flag(gku, out, (
            ("hs", "swh_ocean_qual"), ("sig0", "sig0_ocean_qual")))
        qc_prov["wind_speed_filter"] = "none (no quality flag applied to wind_speed_alt)"
        prov = {"reader": "altimeter_s6",
                "hs_source": "data_01/ku:swh_ocean (MLE retracker; not _nr)",
                "sig0_source": "data_01/ku:sig0_ocean",
                "wind_speed_source": "data_01:wind_speed_alt",
                "rate": "1 Hz (data_01)", "n_rejected_qual": n_qual,
                "n_read": int(g1.sizes["time"]), **qc_prov}
        # Ku and C share variable names, so extras may be qualified 'ku:name'
        # / 'c:name' exactly as `matchup vars` displays them.
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


def read_sentinel1(file, qc=True, extra_vars=None, **_):
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
        out = {"wind_speed": speed, "wind_dir": wdir}
        for src_name, name in (("owiEcmwfWindSpeed", "ecmwf_wind_speed"),
                               ("owiEcmwfWindDirection", "ecmwf_wind_dir")):
            if src_name in src:
                out[name] = src[src_name].values.astype("f8")
        good = s1_good_quality_values(src["owiWindQuality"]) if qc else None
        prov = {
            "reader": "sentinel1",
            "wind_speed_source": "owiWindSpeed", "wind_dir_source": "owiWindDirection",
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


def read_ascat(file, obsLON360=True, **_):
    """ASCAT L2 wind (NUMROWS x NUMCELLS): flatten to a cloud, one time per
    row. QC: wvc_quality_flag < 65536 (same rule as the legacy pipeline)."""
    with xr.open_dataset(file) as src:
        t2d = np.broadcast_to(src["time"].values[..., :1],
                              src["lat"].shape)  # row time across cells
        speed = np.where(src["wvc_quality_flag"].values < 65536,
                         src["wind_speed"].values.astype("f8"), np.nan)
        wdir = np.where(src["wvc_quality_flag"].values < 65536,
                        (src["wind_dir"].values.astype("f8") + 180.0) % 360.0, np.nan)
        return _cloud(t2d, src["lat"].values, src["lon"].values,
                      {"wind_speed": speed, "wind_dir": wdir})


_BUOY_COLS = {  # ISPRA/RON export header -> canonical name
    "hm0": "hs", "hmax": "hmax", "mdir": "wave_dir",
    "tm01": "tm01", "tm02": "tm02", "tp": "tp",
    "la1WindSpd": "wind_speed", "la1WindDir": "wind_dir",
}


def read_buoy_ispra(file, lat=None, lon=None, **_):
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
        if name in ("wind_speed", "wind_dir") and not np.any(np.nan_to_num(vals)):
            dropped.append(src_name)
            continue  # all-zero wind columns: no anemometer on this buoy
        out[name] = vals
        sources[f"{name}_source"] = src_name
    prov = {"reader": "buoy_ispra", "position": f"lat {lat}, lon {lon} (from config)",
            "land_mask": "n/a (moored buoy at a fixed position)",
            "n_rejected_coastal": 0, "n_rejected_qual": 0, "n_read": int(t.size),
            **sources}
    if dropped:
        prov["dropped_all_zero_columns"] = ", ".join(dropped) + " (sensor absent)"
    return _cloud(t, np.full(t.size, float(lat)), np.full(t.size, float(lon)), out,
                  provenance=prov)


READERS = {
    "altimeter_cmems": read_altimeter_cmems,
    "altimeter_s3": read_altimeter_s3,
    "altimeter_s6": read_altimeter_s6,
    "sentinel1": read_sentinel1,
    "ascat": read_ascat,
    "buoy_ispra": read_buoy_ispra,
}


def read_obs(kind, file, **kwargs):
    """Dispatch one obs file to its reader -> canonical cloud (or None)."""
    if kind not in READERS:
        raise KeyError(f"unknown obs kind {kind!r}; known: {sorted(READERS)}")
    return READERS[kind](file, **kwargs)
