"""FieldMatch command line interface."""
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import typer
import xarray as xr
from rich import print as rprint
from rich.console import Console




app = typer.Typer(add_completion=False, no_args_is_help=True,
                  help=("Compare observations and models, or two model grids, using a campaign YAML. "
                        "Start with scan CAMPAIGN, then run CAMPAIGN --describe to preview "
                        "resolved settings without computing or writing results; run CAMPAIGN "
                        "computes all declared comparisons. Plot saved results with your Python script."),
                  epilog="Use fieldmatch COMMAND --help for arguments, defaults and options.")


@app.command()
def doctor():
    """Check FieldMatch and the required data engines."""
    from .doctor import run_doctor
    rprint("[bold]fieldmatch doctor[/bold]")
    if not run_doctor():
        raise typer.Exit(1)
    rprint("[green]all checks passed[/green]")


@app.command()
def scan(campaign: Path = typer.Argument(..., exists=True, dir_okay=False, help="Campaign YAML containing datasets and comparison settings.")):
    """Inventory the files and coverage declared by a campaign YAML."""
    from .campaign import load_campaign
    from .scan import format_report, scan_campaign
    camp = load_campaign(campaign)
    rprint(format_report(camp, scan_campaign(camp)))


@app.command()
def vars(campaign: Path = typer.Argument(..., exists=True, dir_okay=False, help="Campaign YAML; relative paths use the terminal working directory."),
         dataset: str = typer.Argument(..., help="Dataset name in the campaign."),
         all: bool = typer.Option(False, "--all", help="Also list nonstandard fields and alternative time axes/cadences.")):
    """Show standardized and available variables for one dataset."""
    from .campaign import load_campaign
    from .varlist import describe_dataset, format_vars
    camp = load_campaign(campaign)
    print(format_vars(dataset, describe_dataset(camp.get(dataset)), show_all=all))


def _describe(camp, specs):
    from .terminal import describe
    describe(camp, specs)


@app.command(name='info')
def info(result: Path = typer.Argument(..., exists=True, dir_okay=False,
                                      help="Saved comparison CSV/NetCDF or PNG figure."),
         details: bool = typer.Option(False, '--details', help="Also show the complete recorded provenance, including hashes.")):
    """Explain a saved result or figure and check its recorded provenance."""
    from .terminal import result_info
    if not result_info(result, details=details):
        raise typer.Exit(1)


@app.command(name='config-example')
def config_example(output: Optional[Path] = typer.Option(None, '--output', '-o',
                                     help="Write a commented YAML template to a new file; otherwise print it.")):
    """Show all supported YAML settings and examples for every built-in reader."""
    from importlib.resources import files
    template = files('fieldmatch').joinpath('config_example.yaml').read_text()
    if output is None:
        print(template, end='')
    else:
        try:
            with output.open('x') as stream:
                stream.write(template)
        except FileExistsError as exc:
            raise typer.BadParameter(f'{output} already exists; choose a new filename') from exc
        Console().print(f'Configuration template written to {output}', markup=False)


def _formats(value):
    choices = {"csv": ("csv",), "netcdf": ("netcdf",),
               "nc": ("netcdf",), "both": ("csv", "netcdf")}
    value = value.lower()
    if value not in choices:
        raise typer.BadParameter("--format must be csv, netcdf, or both")
    return choices[value]


@app.command()
def collocate(
    campaign: Path = typer.Argument(..., exists=True, dir_okay=False, help="Campaign YAML; relative paths use the terminal working directory."),
    obs: str = typer.Argument(..., help="Observation dataset key in the YAML."), model: str = typer.Argument(..., help="Model dataset key in the YAML."),
    variables: list[str] = typer.Option([], "--variable", "-v", help="Quantity; repeat for independent outputs."),
    format: str = typer.Option("csv", "--format", help="csv, netcdf or both; one output per quantity plus a provenance manifest."),
    tol_minutes: Optional[float] = typer.Option(None, help="Override nearest-time tolerance in minutes; 0 requires exact times. Omit to use YAML/defaults."),
    lead: Optional[str] = typer.Option(None, help="Select forecast hours since initialization, e.g. 24 or 12-35; overrides YAML lead selection."),
    lead_tol: Optional[float] = typer.Option(None, help="Maximum fallback distance in forecast hours when the requested lead is absent. Default 0: no fallback."),
    overlap: Optional[str] = typer.Option(None, help="Resolve multiple forecasts for one valid time: error (default), or explicitly choose shortest_lead."),
    obs_variable: Optional[str] = typer.Option(None, help="Observation source column for one --variable; use YAML mappings for multiple quantities."),
    model_variable: Optional[str] = typer.Option(None, help="Model source field for one --variable; otherwise use the dataset mapping."),
):
    """Advanced: match an obs/model pair directly, without a named comparison."""
    from .campaign import load_campaign
    from .comparison import resolve_comparison, run_comparisons
    if not variables:
        raise typer.BadParameter("select --variable explicitly; inspect available sources with fieldmatch vars")
    if len(variables) != len(set(variables)):
        raise typer.BadParameter("do not repeat the same variable")
    if len(variables)>1 and (obs_variable or model_variable):
        raise typer.BadParameter("source overrides require one variable; use named comparisons for different mappings")
    camp=load_campaign(campaign)
    matching={} if tol_minutes is None else {"tolerance_minutes":tol_minutes}
    opts={k:v for k,v in dict(lead=lead,lead_tol=lead_tol,overlap=overlap).items() if v is not None}
    try:
        specs=[resolve_comparison(camp,obs,model,v,matching=matching,model_options=opts,
                    obs_variable=obs_variable,model_variable=model_variable) for v in variables]
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    _, failures=run_comparisons(camp,specs,formats=_formats(format))
    if failures: raise typer.Exit(1)


@app.command()
def compare(
    campaign: Path = typer.Argument(..., exists=True, dir_okay=False, help="Campaign YAML; relative paths use the terminal working directory."),
    comparison: str = typer.Argument(..., help="Named comparison in the YAML."),
    format: Optional[str] = typer.Option(None, "--format", help="Obs: csv by default. Grids: netcdf; csv gives spatial summaries."),
    describe: bool = typer.Option(False, "--describe", help="Preview effective settings, including defaults. No comparisons or result writes; use scan to check data coverage."),
):
    """Run one named YAML comparison; --describe previews its settings only."""
    from .campaign import load_campaign
    from .comparison import resolve_comparisons, run_comparisons
    camp=load_campaign(campaign)
    if comparison not in camp.comparisons:
        raise typer.BadParameter(f"unknown comparison {comparison!r}; available: {sorted(camp.comparisons)}")
    try:
        specs=resolve_comparisons(camp,comparison)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    if describe:
        _describe(camp, specs); return
    _, failures=run_comparisons(camp,specs,formats=_formats(format or ("netcdf" if specs[0].get("kind")=="grid" else "csv")))
    if failures: raise typer.Exit(1)


@app.command()
def run(
    campaign: Path = typer.Argument(..., exists=True, dir_okay=False, help="Campaign YAML; relative paths use the terminal working directory."),
    format: str = typer.Option("both", "--format", help="csv, netcdf or both (default). Grid CSV contains spatial summaries; plotting fields requires NetCDF."),
    describe: bool = typer.Option(False, "--describe", help="Preview all effective settings, including defaults. No comparisons or result writes; use scan to check data coverage."),
):
    """Run all YAML comparisons; --describe previews settings without computing or writing results."""
    from .campaign import load_campaign
    from .comparison import resolve_comparisons, run_comparisons
    camp = load_campaign(campaign)
    formats = _formats(format)
    try:
        specs = [spec for name in camp.comparisons for spec in resolve_comparisons(camp, name)]
        if not specs:
            raise ValueError("Declare at least one named comparison in the YAML.")
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    if describe:
        _describe(camp, specs)
        return
    _, failures = run_comparisons(camp, specs, formats=formats)
    if failures:
        raise typer.Exit(1)


def _open_pairs(path):
    """Open a portable FieldMatch CSV or NetCDF as an xarray Dataset."""
    path = Path(path)
    if path.suffix.lower() in {".nc", ".netcdf"}:
        return xr.open_dataset(path).load()
    if path.suffix.lower() != ".csv":
        raise typer.BadParameter("pairs must be a .csv or .nc file")
    frame = pd.read_csv(path)
    if "time" in frame:
        frame["time"] = pd.to_datetime(frame["time"], errors="raise")
    for name in ("init", "model_time"):
        if name in frame:
            frame[name] = pd.to_datetime(frame[name], errors="raise")
    ds = xr.Dataset({column: ("obs", frame[column].to_numpy()) for column in frame.columns})
    from .campaign import manifest_path
    import json
    manifest = manifest_path(path.with_suffix(""))
    if manifest.exists():
        record = json.loads(manifest.read_text())
        if record.get('comparison_kind') == 'grid':
            raise typer.BadParameter('grid CSV already contains spatial summaries; use the NetCDF with stats or plotting')
        ds.attrs.update(record.get("pair_attributes", {}))
        variable = ds.attrs.get("variable")
        attrs = record.get("effective", {}).get("observation_attributes", {})
        for name in (variable, f"model_{variable}"):
            if name in ds: ds[name].attrs.update(attrs)
    return ds


def _stats_rows(table, lead_min=None, lead_max=None):
    rows = []
    for variable, values in table.items():
        row = {"variable": variable, **values}
        if lead_min is not None:
            row = {"lead_min": lead_min, "lead_max": lead_max, **row}
        rows.append(row)
    return rows


@app.command()
def stats(
    pairs: Path = typer.Argument(..., exists=True, dir_okay=False,
                                 help="Saved observation pairs (.csv/.nc) or grid comparison (.nc). Keep its manifest beside it."),
    output: Optional[Path] = typer.Option(None, "--output", "-o",
                                          help="Also save the displayed statistics to this CSV path."),
    by_lead: bool = typer.Option(False, "--by-lead",
                                 help="Observation pairs only: score separate forecast lead bins instead of pooling all leads."),
    lead_bin: float = typer.Option(24.0, help="Bin width in forecast hours, used only with --by-lead (e.g. 24 gives [0,24), [24,48))."),
    scatter: bool = typer.Option(False, "--scatter",
                                 help="Save an obs/model scatter PNG beside the input for each variable; requires plot extra, incompatible with --by-lead."),
):
    """Score saved observation pairs or summarize saved grid differences."""
    from .campaign import validate_output_manifest
    from .pairstats import format_stats, plot_scatter, stats_table

    if scatter and by_lead:
        raise typer.BadParameter("--scatter cannot be combined with --by-lead; run the scatter separately")
    if lead_bin <= 0:
        raise typer.BadParameter("--lead-bin must be greater than zero")
    valid, reason, warning = validate_output_manifest(pairs)
    if not valid:
        rprint(f"[red]refusing stale/incomplete output: {reason}[/red]")
        raise typer.Exit(1)
    if warning:
        rprint(f"[yellow]warning: {warning}[/yellow]")
    ds = _open_pairs(pairs)
    if ds.attrs.get('comparison_kind') == 'grid':
        if by_lead or scatter:
            raise typer.BadParameter('grid statistics use saved exact times; select lead windows explicitly; scatter is for observation pairs')
        from .grids import grid_stats
        frame = grid_stats(ds).to_dataframe().reset_index()
        print(frame.to_string(index=False))
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            frame.to_csv(output, index=False, float_format='%.17g')
        return
    rows = []
    if by_lead:
        if "lead_hours" not in ds:
            rprint("[red]no lead_hours column; this is not a forecast collocation[/red]")
            raise typer.Exit(1)
        lead_values = np.asarray(ds["lead_hours"].values, dtype=float)
        for lo in np.arange(0, np.nanmax(lead_values) + lead_bin, lead_bin):
            selected = np.flatnonzero((lead_values >= lo) &
                                      (lead_values < lo + lead_bin))
            if not selected.size:
                continue
            table = stats_table(ds.isel(obs=selected))
            rprint(f"\n[bold]lead {lo:.0f}-{lo + lead_bin:.0f} h[/bold] "
                   f"({selected.size} rows)")
            print(format_stats(table))
            rows.extend(_stats_rows(table, lo, lo + lead_bin))
    else:
        table = stats_table(ds)
        print(format_stats(table))
        rows.extend(_stats_rows(table))
        if "lead_hours" in ds:
            lead_values = np.asarray(ds["lead_hours"].values, dtype=float)
            if np.nanmax(lead_values) - np.nanmin(lead_values) > 1:
                rprint("[yellow]warning: pooled mixed lead times; use --by-lead[/yellow]")
        if scatter:
            try:
                import matplotlib  # noqa: F401
            except ImportError:
                raise typer.BadParameter(
                    "--scatter needs the optional plot dependency: "
                    "python -m pip install -e '.[plot]'")
            for variable in table:
                png = pairs.with_name(f"{pairs.stem}_{variable}_scatter.png")
                plot_scatter(ds, variable, png, title=pairs.stem)
                rprint(f"  scatter -> {png}")
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(rows).to_csv(output, index=False, na_rep="NaN")
        rprint(f"[green]statistics ->[/green] {output}")


if __name__ == "__main__":
    app()
