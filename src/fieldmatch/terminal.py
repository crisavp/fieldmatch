"""Human-readable terminal views of configuration and saved provenance."""
import json
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text


def record_table(record):
    table = Table.grid(padding=(0, 2), expand=False)
    table.add_column(style="cyan", no_wrap=True)
    table.add_column(overflow="fold")
    for key, value in record.items():
        label = key.replace('_', ' ')
        if isinstance(value, dict):
            display = record_table(value) if value else Text('none', style='dim')
        elif value is None:
            display = Text('not set', style='dim')
        elif isinstance(value, (list, tuple)):
            display = (record_table({str(i + 1): v for i, v in enumerate(value)})
                       if any(isinstance(v, dict) for v in value) else
                       Text(', '.join(str(v) for v in value) or 'none'))
        else:
            display = Text(str(value))
        table.add_row(Text(label, style='cyan'), display)
    return table


def describe(camp, specs):
    console = Console()
    console.print(Panel(record_table(dict(campaign=camp.name, configuration=str(camp.path),
                         outputs=str(camp.outdir), period=[str(t) for t in camp.period], region=camp.bbox)),
                        title='Comparison preview', border_style='cyan'))
    console.print('[yellow]Preview only:[/yellow] no comparisons or result files written.')
    console.print('[dim]Use scan to check data coverage. “Not set” means no explicit value at this stage.[/dim]')
    for spec in specs:
        kind = 'GRID' if spec.get('kind') == 'grid' else 'OBS vs MODEL'
        title = Text(f"{spec['comparison']} / {spec['variable']} · {kind}", style='bold green')
        record = {k: v for k, v in spec.items() if k not in
                  {'schema_version', 'campaign', 'comparison', 'variable', 'period', 'region'}}
        console.print(Panel(record_table(record), title=title, border_style='green'))


def result_info(result, *, details=False):
    from .campaign import manifest_path, validate_output_manifest, _file_sha256
    result = Path(result)
    console = Console()
    figure = result.suffix.lower() == '.png'
    if figure:
        hidden = result.parent / '.fieldmatch' / (result.name + '.figure.json')
        legacy = Path(str(result) + '.figure.json')
        metadata = hidden if hidden.exists() else legacy
    else:
        metadata = manifest_path(result.with_suffix(''))
    if not metadata.exists():
        console.print('[yellow]No provenance record found.[/yellow] The file alone cannot explain how it was produced.')
        return False
    try:
        record = json.loads(metadata.read_text())
        if not isinstance(record, dict):
            raise ValueError('record must be a mapping')
        if figure:
            ok = record.get('sha256') == _file_sha256(result)
            reason, warning = ('', '') if ok else ('Figure contents do not match their saved checksum.', '')
            summary = dict(file=str(result), validation='checksum matches' if ok else reason,
                           matplotlib=record.get('matplotlib'), dpi=record.get('dpi'),
                           plots=[dict(plot=p.get('plot'), settings=p.get('settings'),
                                       source=p.get('comparison', {}).get('result_source'),
                                       variable=p.get('comparison', {}).get('variable'))
                                  for p in record.get('plots', [])], axes=record.get('axes', []))
        else:
            ok, reason, warning = validate_output_manifest(result)
            effective = record.get('effective', {})
            summary = dict(file=str(result), status=record.get('status'),
                           validation='passed available checks' if ok else reason,
                           updated=record.get('updated'), comparison=effective.get('comparison'),
                           variable=effective.get('variable'),
                           reference=effective.get('reference_dataset', effective.get('obs_dataset')),
                           model=effective.get('model_dataset'),
                           fieldmatch_version=effective.get('fieldmatch_version'))
            for key in ('rows', 'times', 'common_cells'):
                if key in record:
                    summary[key] = record[key]
            for key in ('period', 'region', 'target_grid', 'matching', 'model_options', 'reader_options'):
                if key in effective:
                    summary[key] = effective[key]
            provenance = effective.get('reader_provenance', {})
            screening = {k:v for k,v in provenance.items()
                         if (k.startswith('n_') or k.endswith('_filter')
                             or k in {'land_mask', 'retained_qc'})}
            if screening:
                summary['reader screening'] = screening
        console.print(Panel(record_table(summary), title='Saved figure' if figure else 'Saved comparison',
                            border_style='green' if ok else 'red'))
        if warning:
            console.print(Text(warning, style='yellow'))
        if details:
            console.print(Panel(record_table(record), title='Full provenance', border_style='cyan'))
        return ok
    except (OSError, ValueError, KeyError) as exc:
        console.print(Text(f'Cannot read provenance: {exc}', style='red'))
        return False
