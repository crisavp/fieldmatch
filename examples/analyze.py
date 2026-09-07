"""Terminal: python analyze.py inspect|run|plot [--config /path/to/harry.yaml].

VS Code: select the installed Python environment, edit INTERACTIVE_CONFIG below,
then run the setup cell and whichever action cell you need. No JupyterLab server.
Paths never fall back to the process working directory.
"""
# %% Setup — imports, settings and functions (run this cell first in VS Code)
from pathlib import Path
import argparse
import html
import json
import numpy as np
import pandas as pd
from fieldmatch.campaign import load_campaign
from fieldmatch.comparison import resolve_comparisons, run_comparisons
from fieldmatch.results import open_result
from fieldmatch.common import common_sample
from fieldmatch.pairstats import stats_table
from fieldmatch.grids import grid_stats

# Only interactive execution needs an explicit absolute configuration path.
# Example: INTERACTIVE_CONFIG = Path('/absolute/path/to/your/study/harry.yaml')
INTERACTIVE_CONFIG = None
MAP_TIME = '2026-01-20T18:00'   # An exact saved timestamp; no nearest substitution.
FIELD_LIMITS = {'hs': (0, 10), 'tp': (0, 18), 'wave_dir': (0, 360)}
DIFFERENCE_LIMITS = {'hs': 2, 'tp': 3, 'wave_dir': 90}
SEVERE_HS = 6.0               # Explicit observed threshold, metres; None disables.


def in_interactive_window():
    try:
        return get_ipython() is not None
    except NameError:
        return False


def config_path(argument=None, *, interactive=False):
    """CLI paths are script-relative; interactive paths must be absolute."""
    if interactive:
        path = Path(argument) if argument is not None else None
        if path is None or not path.is_absolute():
            raise ValueError('Set INTERACTIVE_CONFIG to the absolute path of your YAML, then rerun the setup cell.')
    else:
        base = Path(__file__).resolve().parent
        path = Path(argument) if argument is not None else Path('harry.yaml')
        if not path.is_absolute():
            path = base / path
    return path.resolve(strict=True)


def inspect(campaign):
    """Show resolved files and scientific choices without running comparisons."""
    print(f'Campaign: {campaign.path}\nOutputs: {campaign.outdir}')
    for name, ds in campaign.datasets.items():
        files = ds.files()
        print(f'{name}: {ds.kind}, {len(files)} file(s)')
        if not files:
            print(f'  NO FILES: {ds.paths}')
    specs = [s for name in campaign.comparisons for s in resolve_comparisons(campaign, name)]
    print(json.dumps(specs, indent=2, default=str))
    return specs


def run(campaign):
    """Compute every declared comparison and save both portable formats."""
    specs = [s for name in campaign.comparisons for s in resolve_comparisons(campaign, name)]
    if not specs:
        raise ValueError('Declare at least one named comparison in the YAML.')
    completed, failed = run_comparisons(campaign, specs, formats=('netcdf', 'csv'))
    if failed:
        raise RuntimeError(f'Comparison failures (see manifests): {failed}')
    return completed


def load_results(campaign):
    """Load only this campaign's declared quantities; validate each saved result."""
    records = {}
    for file in campaign.outdir.glob('*.manifest.json'):
        record = json.loads(file.read_text())
        effective = record.get('effective', {})
        if effective.get('campaign') != campaign.name:
            continue
        key = (effective.get('comparison'), effective.get('variable'))
        if key in records:
            raise ValueError(f'Multiple result manifests for {key}; use a separate output folder per study.')
        records[key] = record
    loaded = {}
    for name, declaration in campaign.comparisons.items():
        for variable in declaration['variables']:
            record = records.get((name, variable))
            if record is None or record['status'] != 'complete':
                raise ValueError(f'No complete {name}/{variable} result. Run comparisons first.')
            # Validate against the currently selected campaign too, not just the
            # campaign path embedded in an output made with a different YAML.
            from fieldmatch.campaign import pair_digest
            first = declaration.get('obs', declaration.get('reference'))
            if record.get('pair_digest') != pair_digest(campaign, first, declaration['model']):
                raise ValueError(f'{name}/{variable}: current configuration differs; rerun comparisons.')
            output = record.get('outputs', {}).get('netcdf')
            if output is None:
                raise ValueError(f'{name}/{variable} needs NetCDF; run with both formats.')
            loaded[(name, variable)] = open_result(output)
    if not loaded:
        raise ValueError('No declared results to plot.')
    return loaded


def plot(campaign, *, show=False, map_time=MAP_TIME):
    """Read saved results, explicitly align station samples, score and draw.

    Returns tables, pair groups, grid results and figures for interactive inspection.
    This function never recomputes a comparison or regrids a field.
    """
    import matplotlib
    if not show and not in_interactive_window():
        matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from fieldmatch.plotting import time_series, scatter, comparison_panels, save_figure

    loaded = load_results(campaign)
    destination = campaign.outdir / 'figures'
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
    def save(fig, filename):
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
            save(fig, f'{obs}_{variable}_series.png')
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
        save(fig, f'{obs}_{variable}_scatter.png')

    for (name, variable), grid in grids.items():
        summary = grid_stats(grid).to_dataframe()
        tables[f'{name}_{variable}_spatial'] = summary
        print(f'\n{name}/{variable} — spatial differences (first five times)\n{summary.head().to_string()}')
        fig, axes = comparison_panels(grid, map_time, clim=FIELD_LIMITS.get(variable),
                                      difference_limit=DIFFERENCE_LIMITS.get(variable))
        save(fig, f'{name}_{variable}_panels.png')

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


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['inspect', 'run', 'plot'])
    parser.add_argument('--config', help='YAML path: absolute, or relative to this script (not the working directory).')
    parser.add_argument('--show', action='store_true', help='Plot action: also display Matplotlib windows; needs a graphical backend.')
    parser.add_argument('--time', default=MAP_TIME, help='Plot action: exact grid timestamp.')
    args = parser.parse_args(argv)
    if args.show and args.action != 'plot':
        parser.error('--show is only used by plot')
    try:
        campaign = load_campaign(config_path(args.config))
        if args.action == 'inspect':
            inspect(campaign)
        elif args.action == 'run':
            run(campaign)
        else:
            plot(campaign, show=args.show, map_time=args.time)
    except (ValueError, RuntimeError, OSError, KeyError) as exc:
        parser.exit(1, f'{exc}\n')


if __name__ == '__main__' and not in_interactive_window():
    main()

# %% Inspect — interactive only; choose INTERACTIVE_CONFIG in the setup cell
if __name__ == '__main__' and in_interactive_window():
    campaign = load_campaign(config_path(INTERACTIVE_CONFIG, interactive=True))
    specifications = inspect(campaign)

# %% Run comparisons — interactive only; skip this cell when reusing saved results
if __name__ == '__main__' and in_interactive_window():
    completed = run(campaign)

# %% Plot and inspect — interactive only; no model loading or matching here
if __name__ == '__main__' and in_interactive_window():
    analysis = plot(campaign, show=True, map_time=MAP_TIME)
    tables, pairs, grids = analysis['tables'], analysis['pairs'], analysis['grids']
