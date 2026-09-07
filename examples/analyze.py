"""Prepare results first in your terminal (use your actual YAML path):

    fieldmatch scan /path/to/study/harry.yaml
    fieldmatch run /path/to/study/harry.yaml --describe
    fieldmatch run /path/to/study/harry.yaml

Then set CONFIG below and run this file, or its cells in VS Code.
This script only reads saved comparisons, computes summaries and plots.
"""
# %% Settings and plotting functions
from pathlib import Path
import html
import numpy as np
import pandas as pd
from fieldmatch.campaign import load_campaign
from fieldmatch.results import open_campaign_results
from fieldmatch.common import common_sample
from fieldmatch.pairstats import stats_table
from fieldmatch.grids import grid_stats

# One explicit path works in both terminal and cells, from any working directory.
CONFIG = Path('/absolute/path/to/study/harry.yaml')
SHOW = True                  # Display figures using your Matplotlib backend.
SAVE = True                  # Save PNG, provenance, CSV and HTML under results/figures.
MAP_TIME = '2026-01-20T18:00'  # Exact saved timestamp; no nearest substitution.
FIELD_LIMITS = {'hs': (0, 10), 'tp': (0, 18), 'wave_dir': (0, 360)}
DIFFERENCE_LIMITS = {'hs': 2, 'tp': 3, 'wave_dir': 90}
SEVERE_HS = 6.0               # Observed threshold in metres; None disables.


def plot(campaign, *, show=True, save=True, map_time=MAP_TIME):
    """Read saved results, explicitly align station samples, score and draw.

    Returns tables, pair groups, grid results and figures for interactive inspection.
    This function never recomputes a comparison or regrids a field.
    """
    import matplotlib
    if not show:
        matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from fieldmatch.plotting import time_series, scatter, comparison_panels, save_figure

    loaded = open_campaign_results(campaign)
    destination = campaign.outdir / 'figures'
    if save:
        destination.mkdir(parents=True, exist_ok=True)
    groups, grids = {}, {}
    for (name, variable), ds in loaded.items():
        if ds.attrs.get('comparison_kind') == 'grid':
            # Check requested map times before writing any new figures.
            if np.datetime64(map_time, 'ns') not in ds.time.values:
                raise ValueError(f'{name}: {map_time} is not an exact saved time; inspect grid.time.values.')
            grids[(name, variable)] = ds
        else:
            obs = campaign.comparisons[name]['obs']
            groups.setdefault((obs, variable), {})[name] = ds

    figures, images, tables, aligned_groups = [], [], {}, {}
    def record_figure(fig, filename):
        if save:
            images.append(save_figure(fig, destination / filename))
        figures.append(fig)

    for (obs, variable), pairs in groups.items():
        aligned, counts = common_sample(pairs)  # An explicit analysis decision.
        aligned_groups[(obs, variable)] = aligned
        first = next(iter(aligned.values()))
        if not first.sizes['obs']:
            raise ValueError(f'{obs}/{variable}: no common observations; inspect coverage and matching.')
        scores = pd.DataFrame({name: stats_table(ds)[variable] for name, ds in aligned.items()}).T
        tables[f'{obs}_{variable}_scores'] = scores
        tables[f'{obs}_{variable}_counts'] = pd.DataFrame(counts).T
        print(f'\n{obs}/{variable} — common observations\n{scores.to_string()}')
        if variable == 'hs' and SEVERE_HS is not None:
            keep = np.flatnonzero(first.hs.values >= SEVERE_HS)
            tables[f'{obs}_{variable}_severe_scores'] = pd.DataFrame({
                name: stats_table(ds.isel(obs=keep))[variable] for name, ds in aligned.items()}).T
        fixed_station = len(np.unique(first.lat)) == len(np.unique(first.lon)) == 1
        if fixed_station:
            fig, ax = time_series(aligned, title=f'{obs}: {variable}, common observations')
            if variable in FIELD_LIMITS:
                ax.set_ylim(*FIELD_LIMITS[variable])
            record_figure(fig, f'{obs}_{variable}_series.png')
        else:
            print('Moving observations: scatter plots only; station time series omitted.')
        n = len(aligned)
        fig, axes = plt.subplots((n + 2) // 3, min(n, 3), figsize=(5 * min(n, 3), 4 * ((n + 2) // 3)), constrained_layout=True)
        axes = np.atleast_1d(axes).ravel()
        for ax, (name, ds) in zip(axes, aligned.items()):
            scatter(ds, ax=ax, title=name)
            if variable in FIELD_LIMITS:
                ax.set(xlim=FIELD_LIMITS[variable], ylim=FIELD_LIMITS[variable])
        for ax in axes[n:]:
            ax.set_visible(False)
        record_figure(fig, f'{obs}_{variable}_scatter.png')

    for (name, variable), grid in grids.items():
        summary = grid_stats(grid).to_dataframe()
        tables[f'{name}_{variable}_spatial'] = summary
        print(f'\n{name}/{variable} — spatial differences (first five times)\n{summary.head().to_string()}')
        fig, axes = comparison_panels(grid, map_time, clim=FIELD_LIMITS.get(variable),
                                      difference_limit=DIFFERENCE_LIMITS.get(variable))
        record_figure(fig, f'{name}_{variable}_panels.png')

    if save:
        for name, table in tables.items():
            table.to_csv(destination / f'{name}.csv', float_format='%.17g')
        body = '<h1>' + html.escape(campaign.name) + '</h1>'
        body += '<p>Prepared comparisons; grid difference = model minus reference. Station scores use common observations.</p>'
        for name, table in tables.items():
            body += '<h2>' + html.escape(name) + '</h2>' + table.head(10).to_html() + '<p>Full table: ' + html.escape(name) + '.csv</p>'
        for path in images:
            body += '<h2>' + html.escape(path.stem) + '</h2><img src="' + html.escape(path.name) + '">'
        gallery = destination / 'index.html'
        gallery.write_text('<!doctype html><meta charset="utf-8"><title>FieldMatch analysis</title>'
            '<style>body{font:16px/1.5 system-ui;max-width:1200px;margin:30px auto;padding:0 20px}img{max-width:100%}table{border-collapse:collapse;display:block;overflow:auto}td,th{padding:6px}</style>' + body)
        print(f'\nFigures and full tables: {destination}\nOpen in a browser: {gallery}')
    if show:
        plt.show()
    else:
        for fig in figures:
            plt.close(fig)
    return dict(tables=tables, pairs=aligned_groups, grids=grids, figures=figures, loaded=loaded)


# %% Load saved results and plot — identical execution in terminal and VS Code
if not CONFIG.is_absolute():
    raise ValueError('Set CONFIG to the absolute path of your campaign YAML.')
campaign = load_campaign(CONFIG)
analysis = plot(campaign, show=SHOW, save=SAVE, map_time=MAP_TIME)
tables, pairs, grids = analysis['tables'], analysis['pairs'], analysis['grids']
