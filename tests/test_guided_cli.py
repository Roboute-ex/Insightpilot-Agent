"""CLI advice success is distinct from successful analysis; blocked exports stay zero."""
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch
import pandas as pd
import pytest
from insightpilot import cli


def run_cli(arguments, capsys):
    frame = pd.DataFrame({'date': pd.date_range('2026-01-01', periods=16), 'orders': list(range(16))})
    with patch.object(sys, 'argv', ['insightpilot', '--data-source', 'file', '--input-file', 'unused.csv', '--table-name', 'daily', '--date-column', 'date', '--metric-columns', 'orders', '--question', '昨日订单量为什么下降？', '--output-format', 'json', *arguments]), patch.object(cli, '_load_file_tables', return_value=({'daily': frame}, None, '')):
        code = cli.main()
    return code, json.loads(capsys.readouterr().out)


def test_advise_only_does_not_analyze_or_export(capsys):
    with patch.object(cli, 'run_agent_analysis', side_effect=AssertionError('analysis')) as run, patch.object(cli, '_generate_requested_exports', side_effect=AssertionError('exports')) as export:
        code, payload = run_cli(['--advise-only', '--playbook', 'causal_exploration'], capsys)
    assert code == 0  # Asking for advice succeeded; execution remains blocked.
    assert run.call_count == export.call_count == 0
    assert payload['runs'][0]['execution_status'] == 'NOT_STARTED'
    assert payload['runs'][0]['analysis_advice']['can_submit'] is False


def test_blocked_execution_nonzero_and_no_report(capsys):
    with patch.object(cli, '_generate_requested_exports', side_effect=AssertionError('exports')) as export, patch.object(cli, 'write_text_report', side_effect=AssertionError('report')) as report:
        code, payload = run_cli(['--playbook', 'causal_exploration', '--export-format', 'pdf'], capsys)
    assert code == 2
    assert export.call_count == report.call_count == 0
    result = payload['runs'][0]
    assert result['execution_status'] == 'NEEDS_INPUT'
    assert result['report_path'] is None
    assert result['preflight']['blocking_issues']


@pytest.mark.parametrize('method', ['auto', '__legacy__'])
@pytest.mark.parametrize('advise_only', [True, False])
def test_virtual_method_choices_work_in_real_cli(tmp_path, method, advise_only):
    source = tmp_path / 'daily.csv'
    pd.DataFrame({'date': pd.date_range('2026-01-01', periods=16), 'orders': list(range(16))}).to_csv(source, index=False)
    destination = tmp_path / 'exports'
    command = [sys.executable, 'examples/run_demo.py', '--data-source', 'file',
               '--input-file', str(source), '--table-name', 'daily', '--date-column', 'date',
               '--metric-columns', 'orders', '--question', '昨日订单量为什么下降？',
               '--playbook', method, '--output-format', 'json', '--export-dir', str(destination)]
    if advise_only:
        command.append('--advise-only')
    process = subprocess.run(command, cwd=Path(__file__).resolve().parents[1],
                             env={**os.environ, 'PYTHONIOENCODING': 'utf-8'},
                             capture_output=True, text=True, encoding='utf-8', timeout=45)
    assert process.returncode == 0, process.stderr
    run = json.loads(process.stdout)['runs'][0]
    assert run['execution_status'] == ('NOT_STARTED' if advise_only else 'COMPLETED')
    assert run['analysis_advice']['effective_method']['method_ref'] == 'route:legacy'
    assert run['analysis_advice']['can_submit'] is True
    if advise_only:
        assert not destination.exists()
    else:
        assert Path(run['report_path']).is_file()


@pytest.mark.parametrize('method', ['auto', '__legacy__'])
def test_virtual_methods_do_not_bypass_unsupported_goal_in_real_cli(tmp_path, method):
    source = tmp_path / 'daily.csv'
    pd.DataFrame({'date': pd.date_range('2026-01-01', periods=16), 'orders': list(range(16))}).to_csv(source, index=False)
    destination = tmp_path / 'exports'
    process = subprocess.run(
        [sys.executable, 'examples/run_demo.py', '--data-source', 'file', '--input-file', str(source),
         '--table-name', 'daily', '--date-column', 'date', '--metric-columns', 'orders',
         '--question', '预测未来30天订单量', '--playbook', method, '--output-format', 'json',
         '--export-format', 'pdf', '--export-dir', str(destination)],
        cwd=Path(__file__).resolve().parents[1], env={**os.environ, 'PYTHONIOENCODING': 'utf-8'},
        capture_output=True, text=True, encoding='utf-8', timeout=45)
    assert process.returncode == 2, process.stderr
    run = json.loads(process.stdout)['runs'][0]
    assert run['execution_status'] == 'UNSUPPORTED'
    assert run['preflight']['blocking_issues']
    assert run['analysis_advice']['can_submit'] is False
    assert run['report_path'] is None
    assert run['export_paths'] == []
    assert not destination.exists()


@pytest.mark.parametrize('window, can_submit', [('2', True), ('0', False)])
def test_auto_parameters_reach_resolved_method_validation(capsys, window, can_submit):
    code, payload = run_cli(['--advise-only', '--playbook', 'auto', '--question', '订单量趋势如何？',
                             '--rolling-window', window], capsys)
    assert code == 0
    run = payload['runs'][0]
    assert run['analysis_advice']['effective_method']['method_ref'] == 'playbook:metric_trend'
    assert run['normalized_request']['playbook_parameters']['rolling_window'] == int(window)
    assert run['analysis_advice']['can_submit'] is can_submit
    if not can_submit:
        assert any(issue['code'] == 'INVALID_PARAMETER' for issue in run['preflight']['blocking_issues'])
