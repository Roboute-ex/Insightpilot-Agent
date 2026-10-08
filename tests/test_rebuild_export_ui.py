"""Regression checks for restored exports and actual UI state transitions."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
from zipfile import ZipFile
import json

import openpyxl
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from insightpilot.reports.bundle import generate_export_bundle
from insightpilot.reports.excel import generate_excel_report
from insightpilot.reports.html import generate_html_report
from insightpilot.reports.manifest import RunManifest, sanitize_manifest_value
from insightpilot.ui.experiment_display import experiment_display
from insightpilot.visualization.factory import build_chart
from insightpilot.visualization.specs import ChartSpec


def test_excel_defaults_to_chinese_and_neutralizes_formula_cells(transaction_result):
    result = dict(transaction_result)
    result['question'] = '=HYPERLINK("https://invalid.example","click")'
    result['result_tables'] = {'injection': pd.DataFrame({'label': ['=1+1', ' \t@SUM(1)', '-formula', '+formula', '正常'], 'value': [-2, 3, 4, 5, 6]})}
    workbook = openpyxl.load_workbook(BytesIO(generate_excel_report(result, RunManifest.from_dict(result['run_manifest']))))
    assert not {'Summary', 'Findings', 'Reviewer', 'Mapping', 'Manifest'}.intersection(workbook.sheetnames)
    assert not any(cell.data_type == 'f' for sheet in workbook for row in sheet for cell in row)
    sheet = workbook['结果_injection']
    assert sheet['A2'].value == "'=1+1"
    assert sheet['B2'].value == -2


def test_zip_csv_formula_safety_and_truncation(monkeypatch):
    import insightpilot.reports.bundle as module
    monkeypatch.setattr(module, 'MAX_CSV_ROWS', 2)
    content = generate_export_bundle('# 中文', '<html></html>', b'x', '{}', {'../unsafe': pd.DataFrame({'x': ['=1+1', ' \t@SUM(1)', 'third']})})
    with ZipFile(BytesIO(content)) as archive:
        names = archive.namelist()
        assert 'report.pdf' in names
        csv_name = next(name for name in names if name.startswith('results/'))
        assert '..' not in csv_name
        text = archive.read(csv_name).decode('utf-8-sig')
        assert "'=1+1" in text and 'third' not in text
        assert '原 3 行，导出前 2 行' in archive.read('README.txt').decode('utf-8')


def test_manifest_rejects_unknown_fields_and_invalid_types(transaction_result):
    values = dict(transaction_result['run_manifest'])
    with pytest.raises(ValueError, match='未知字段'):
        RunManifest.from_dict({**values, 'execute_after_import': True})
    with pytest.raises(ValueError, match='array'):
        RunManifest.from_dict({**values, 'route_taken': 'execute'})


def test_manifest_redacts_url_query_and_filter_values():
    values = {'question': '错误 https://service.example/path?token=do-not-leak&mode=read',
              'source_summary': {'database_url': 'postgresql://user:password@host/db?token=query-secret'},
              'metric_request': {'filters': [{'dimension': 'customer_city', 'operator': 'eq', 'value': 'private-filter'}]},
              'parameters': ['query-scalar'], 'nan': float('nan')}
    encoded = json.dumps(sanitize_manifest_value(values), ensure_ascii=False, allow_nan=False)
    for value in ['do-not-leak', 'query-secret', 'private-filter', 'query-scalar']:
        assert value not in encoded


def test_experiment_formats_use_actual_level_points_and_nonzero_p_value():
    formatted = experiment_display({'metric_id': 'completion_rate', 'absolute_lift': .05, 'relative_lift': .1,
                                    'confidence_level': .9, 'confidence_interval_lower': .02, 'confidence_interval_upper': .08, 'p_value': 1e-15})
    assert formatted['绝对提升（lift）'] == '5 个百分点'
    assert '90% 置信区间（实验组减对照组的绝对差）' in formatted
    assert formatted['p-value'] == '1e-15'


def test_charts_preserve_numeric_periods_funnel_order_and_missing_retention():
    line = build_chart(ChartSpec('line', 'line', '周期', 't', x='period', y=['value']), {'t': pd.DataFrame({'period': [0, 1, 2], 'value': [1, .8, .6]})})
    assert list(line.data[0].x) == [0, 1, 2]
    funnel = build_chart(ChartSpec('f', 'funnel', '漏斗', 't', x='stage', y=['count']), {'t': pd.DataFrame({'stage': ['访问', '支付'], 'count': [100, 25]})})
    assert list(funnel.data[0].x) == [100, 25]
    assert list(funnel.data[0].y) == ['访问', '支付']
    heat = build_chart(ChartSpec('h', 'heatmap', '留存', 't', x='period', y=['rate'], color='cohort'), {'t': pd.DataFrame({'cohort': ['A', 'A', 'B', 'B'], 'period': [0, 1, 0, 1], 'rate': [1., .5, 1., float('nan')]})})
    assert heat.data[0].hoverongaps is False


def test_html_escapes_chart_and_question_text_offline(transaction_result):
    result = dict(transaction_result)
    result['question'] = '<script>report-injection</script>'
    fig = build_chart(ChartSpec('safe', 'bar', '<script>chart-injection</script>', 't', x='label', y=['value']), {'t': pd.DataFrame({'label': ['<img src=x onerror=alert(1)>'], 'value': [1]})})
    content = generate_html_report(result, [fig, fig], RunManifest.from_dict(result['run_manifest']))
    assert '<script>report-injection</script>' not in content
    assert '<script>chart-injection</script>' not in content
    assert '<img src=x onerror=alert(1)>' not in content
    assert 'src="https://cdn.plot.ly' not in content
    assert content.count('plotly.js v') == 1


def test_actual_preview_execute_mode_change_and_stale_result():
    path = Path(__file__).resolve().parents[1] / 'app' / 'ui_streamlit.py'
    app = AppTest.from_file(str(path), default_timeout=90)
    app.session_state['demo_scale']='small'
    app.run()
    app.session_state['guided_plan']=True; app.run()
    next(item for item in app.button if item.label == '预览分析方案').click().run()
    assert not app.exception
    preview = app.session_state['last_analysis_result']
    assert preview['execution_mode'] == 'plan_only'
    assert not any(step.startswith('run_') or step == 'execute_query_plan' for step in preview['route_taken'])
    next(item for item in app.button if item.label == '开始分析').click().run()
    assert not app.exception
    executed = app.session_state['last_analysis_result']
    assert executed['execution_mode'] == 'execute'
    assert any(isinstance(frame, pd.DataFrame) and not frame.empty for frame in executed['result_tables'].values())
    run_id = executed['run_manifest']['run_id']
    for opened in [True, False, True]:
        app.session_state['guided_advanced'] = opened; app.run()
        assert not app.exception
        assert app.session_state['last_analysis_result']['run_manifest']['run_id'] == run_id
    app.text_input(key='question').set_value('请改为收入趋势分析').run()
    assert any('上次成功结果' in item.value for item in app.warning)
    assert app.session_state['last_analysis_result']['run_manifest']['run_id'] == run_id


def test_example_question_applies_goal_mapping_and_playbook():
    path = Path(__file__).resolve().parents[1] / 'app' / 'ui_streamlit.py'
    app = AppTest.from_file(str(path), default_timeout=90)
    app.session_state['demo_scale']='small'
    app.run()
    next(item for item in app.button if str(item.key).startswith('guided_example_')).click().run()
    assert not app.exception
    settings = app.session_state['example_settings']
    assert app.session_state['goal_mode_selector'] == 'auto'
    assert app.session_state['playbook_selector'] == 'auto'
    assert app.session_state['guided_selection_source'] == 'example_applied'
    assert app.session_state['question'] == settings['question']
    next(item for item in app.button if item.label == '开始分析').click().run()
    assert not app.exception
    result = app.session_state['last_analysis_result']
    assert result['goal_mode'] == settings['goal_mode']
    assert result['column_mapping']['metric_columns'] == settings['column_mapping']['metric_columns']


def test_upload_helper_reads_selected_excel_sheets_and_csv_options():
    from app.components.data_source_panel import load_uploaded_registry
    excel = BytesIO()
    excel.name = '模拟.xlsx'
    with pd.ExcelWriter(excel, engine='openpyxl') as writer:
        pd.DataFrame({'指标': [1]}).to_excel(writer, sheet_name='甲表', index=False)
        pd.DataFrame({'指标': [2]}).to_excel(writer, sheet_name='乙表', index=False)
    registry = load_uploaded_registry([excel], {0: {'sheets': ['甲表', '乙表']}})
    assert len(registry.list_tables()) == 2
    assert sorted(frame.iloc[0, 0] for frame in registry.to_duckdb_tables().values()) == [1, 2]
    csv = BytesIO('日期;订单\n2026-01-01;7\n'.encode('gbk'))
    csv.name = '模拟.csv'
    registry = load_uploaded_registry([csv], {0: {'encoding': 'gbk', 'sep': ';'}})
    frame = next(iter(registry.to_duckdb_tables().values()))
    assert list(frame.columns) == ['日期', '订单']
    assert frame.iloc[0]['订单'] == 7


def test_preparing_exports_preserves_selected_report_tab():
    path = Path(__file__).resolve().parents[1] / 'app' / 'ui_streamlit.py'
    app = AppTest.from_file(str(path), default_timeout=90)
    app.session_state['demo_scale']='small'
    app.run()
    next(item for item in app.button if item.label == '开始分析').click().run()
    app.session_state['requested_result_tab'] = '报告导出'
    app.run()
    next(item for item in app.button if item.label == '生成 PDF 报告').click().run()
    assert not app.exception
    assert app.session_state['result_tabs'] == '报告导出'
    from app.components.export_panel import export_cache_key
    result = app.session_state['last_analysis_result']
    cache = app.session_state['performance_export_cache']
    assert cache.get(export_cache_key(result, 'pdf')).startswith(b'%PDF')
    assert cache.get(export_cache_key(result, 'excel')) is None
    app.run()
    assert app.session_state['result_tabs'] == '报告导出'
    next(item for item in app.button if item.label == '生成 PDF 报告').click().run()
    assert not app.exception and app.session_state['result_tabs'] == '报告导出'
    assert app.session_state['last_analysis_result']['run_manifest']['run_id'] == result['run_manifest']['run_id']


def test_synthetic_labels_do_not_rewrite_custom_data():
    from app.components.result_panel import _localized_frame
    from insightpilot.ui.synthetic_display import synthetic_display_text
    frame = pd.DataFrame({'dimension': ['city'], 'dimension_value': ['South City'], 'contribution_value': [-2]})
    builtin = _localized_frame(frame, 'demo', synthetic=True)
    custom = _localized_frame(frame, 'demo', synthetic=False)
    assert '南城' in builtin.to_string()
    assert 'South City' in custom.to_string()
    assert frame.iloc[0]['dimension_value'] == 'South City'
    assert synthetic_display_text('platform:移动应用 user_segment:new HIGH') == '平台:移动应用 用户分层:新客 高风险'
