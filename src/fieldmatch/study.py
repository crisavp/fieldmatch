"""Small Python-first interface to the datasets declared in a campaign file."""
import numpy as np
import xarray as xr

from .campaign import MODEL_KINDS, combine_provenance, crop_obs, load_campaign
from .models import open_model
from .readers import read_obs


_UNSET = object()


class Study:
    """Open named observations and model views from one dataset catalogue.

    The YAML describes how files are read.  Initialization and lead overrides
    belong at the call site so a scientific script shows the forecast view it
    actually analyses.
    """

    def __init__(self, config):
        self.campaign = load_campaign(config)
        self._cache = {}

    @property
    def datasets(self):
        return tuple(self.campaign.datasets)

    def open_observations(self, name):
        """Read, combine and campaign-crop one named observation dataset."""
        declared = self.campaign.get(name)
        if declared.role != "obs":
            raise ValueError(f"{name!r} is a model dataset")
        key = ("observations", name)
        if key in self._cache:
            return self._cache[key]
        files = declared.files()
        if not files:
            raise FileNotFoundError(f"no files match observation dataset {name!r}")
        pieces = []
        for filename in files:
            part = read_obs(declared.kind, filename, **declared.options)
            if part is not None:
                part = crop_obs(part, self.campaign.bbox, self.campaign.period)
                if part is not None:
                    pieces.append(part)
        if not pieces:
            raise ValueError(f"no {name!r} observations inside the study region and period")
        result = xr.concat(pieces, dim="obs").sortby("time")
        result.attrs = combine_provenance(pieces)
        if "obs_id" in result and len(np.unique(result.obs_id)) != result.sizes["obs"]:
            raise ValueError(f"{name!r} contains duplicate observation IDs")
        result.attrs.update(fieldmatch_dataset=name, fieldmatch_campaign=self.campaign.name)
        self._cache[key] = result
        return result

    def open_model(self, name, *, variables=None, init=_UNSET,
                   init_cycle=_UNSET, lead=_UNSET, lead_tol=_UNSET):
        """Open one selected model view; keyword selectors override the YAML."""
        declared = self.campaign.get(name)
        if declared.role != "model":
            raise ValueError(f"{name!r} is an observation dataset")
        options = dict(declared.options)
        overrides = {"init": init, "init_cycle": init_cycle,
                     "lead": lead, "lead_tol": lead_tol}
        for option, value in overrides.items():
            if value is not _UNSET:
                if value is None:
                    options.pop(option, None)
                else:
                    options[option] = value
        if options.get("init") is not None and options.get("init_cycle") is not None:
            raise ValueError("select either init or init_cycle, not both")
        if isinstance(variables, str):
            variables = [variables]
        requested = None if variables is None else tuple(dict.fromkeys(
            source
            for variable in variables
            for source in (("u10", "v10") if variable in {"wind_speed", "wind_dir"}
                           else (variable,))
        ))
        key = ("model", name, requested, repr(sorted(options.items())))
        if key in self._cache:
            return self._cache[key]
        result = open_model(
            declared.paths,
            engine=MODEL_KINDS[declared.kind],
            variables=requested,
            bbox=self.campaign.bbox,
            period=self.campaign.period,
            time_pad=np.timedelta64(0, "s"),
            **options,
        ).load()
        result.attrs.update(fieldmatch_dataset=name, fieldmatch_campaign=self.campaign.name)
        self._cache[key] = result
        return result

    def open(self, name, **kwargs):
        """Open a named dataset, dispatching to its observation or model reader."""
        declared = self.campaign.get(name)
        if declared.role == "obs":
            if kwargs:
                raise TypeError("observation reader choices belong in the dataset catalogue")
            return self.open_observations(name)
        return self.open_model(name, **kwargs)
