"""Minimal use of FieldMatch's Python building blocks.

Run ``python examples/create_demo_data.py`` first. Most users should prefer the
campaign CLI, which also handles cropping, multiple files and manifests.
"""
from pathlib import Path

from fieldmatch.collocate_track import collocate_track, write_pairs
from fieldmatch.models import open_model
from fieldmatch.readers import read_obs


HERE = Path(__file__).resolve().parent


def main():
    observations = read_obs("altimeter_cmems", HERE / "data" / "altimeter.nc")
    model = open_model(HERE / "data" / "model.nc", engine="netcdf4")
    pairs = collocate_track(observations, model, variable="hs")
    outputs = write_pairs(pairs, HERE / "results" / "python_api_pairs")
    print(outputs["csv"])


if __name__ == "__main__":
    main()
