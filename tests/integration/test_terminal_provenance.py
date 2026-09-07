from pathlib import Path
import json
from importlib.resources import files
import inspect
import yaml
from rich.console import Console
from typer.testing import CliRunner
from fieldmatch.cli import app
from fieldmatch.campaign import load_campaign, MODEL_OPTIONS, manifest_path, validate_output_manifest
from fieldmatch.comparison import MATCHING_DEFAULTS, resolve_comparisons
from fieldmatch.readers import READERS
from fieldmatch.terminal import record_table


def test_installed_template_covers_reader_and_model_options(tmp_path):
    runner = CliRunner()
    target = tmp_path/'reference.yaml'
    result = runner.invoke(app, ['config-example', '--output', str(target)])
    assert result.exit_code == 0, result.output
    original = target.read_bytes()
    assert runner.invoke(app, ['config-example', '--output', str(target)]).exit_code != 0
    assert target.read_bytes() == original
    raw = yaml.safe_load(target.read_text())
    camp = load_campaign(target)
    covered = {d.kind: d for d in camp.datasets.values()}
    assert set(READERS) <= set(covered)
    for kind, spec in READERS.items():
        assert set(covered[kind].options) == set(spec.options)
        params = inspect.signature(spec.reader).parameters
        for key in spec.options - {'lat', 'lon'}:
            expected = params[key].default
            actual = covered[kind].options[key]
            assert actual == expected or (key == 'extra_vars' and actual == [] and expected is None)
    for kind in ['grib', 'netcdf']:
        assert set(covered[kind].options) == MODEL_OPTIONS
    assert set(raw['matching_defaults']) == set(MATCHING_DEFAULTS)
    for name in camp.comparisons:
        assert resolve_comparisons(camp, name)
    console = Console(force_terminal=True, no_color=False, color_system="standard", width=80, record=True)
    with console.capture() as capture:
        console.print(record_table({'time_method': 'exact', 'tolerance_minutes': 0}))
    assert '\x1b[' in capture.get() and 'exact' in capture.get()


def test_legacy_provenance_and_hidden_precedence(tmp_path):
    # Failed/running state must remain authoritative when both layouts exist.
    result = tmp_path/'pair.csv'; result.write_text('x\n1\n')
    legacy = result.with_suffix('.manifest.json')
    legacy.write_text(json.dumps({'status': 'complete'}))
    assert manifest_path(result.with_suffix('')) == legacy
    assert validate_output_manifest(result)[0]
    hidden = manifest_path(result.with_suffix(''), writing=True)
    hidden.parent.mkdir()
    hidden.write_text(json.dumps({'status': 'running'}))
    assert manifest_path(result.with_suffix('')) == hidden
    assert not validate_output_manifest(result)[0]
    r = CliRunner().invoke(app, ['info', str(result)])
    assert r.exit_code == 1 and 'running' in r.output
    hidden.write_text('{bad json')
    r = CliRunner().invoke(app, ['info', str(result)])
    assert r.exit_code == 1 and 'Cannot read provenance' in r.output
