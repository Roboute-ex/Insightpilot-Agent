"""Small independent contracts for method advice and execution gates."""
import copy
from unittest.mock import patch

import pandas as pd
import pytest

from insightpilot.agents.dataset import PreparedDataset
from insightpilot.agents.workflow import run_agent_analysis
from insightpilot.planning.planner import prepare_analysis_request


def daily():
    return pd.DataFrame({"date": pd.date_range("2026-01-01", periods=16), "orders": list(range(16)), "city": ["A", "B"] * 8})


def prepare(frame=None, **kwargs):
    dataset = PreparedDataset.from_tables({"daily": daily() if frame is None else frame}, dataset_id="fixture", revision="r1")
    request = {"question": "订单量趋势如何？", "playbook_id": "metric_trend", "column_mapping": {"table_name": "daily", "date_column": "date", "metric_columns": ["orders"], "aggregation": "sum"}, **kwargs}
    return dataset, request


def advise(dataset, request, **kwargs):
    return prepare_analysis_request(**request, table_metadata=dataset.metadata, dataset_revision=dataset.revision, **kwargs)


def test_advisor_has_no_scan_query_stats_or_report():
    dataset, request = prepare()
    with patch("pandas.Series.nunique", side_effect=AssertionError("scan")), patch("insightpilot.reports.manifest.fingerprint_dataframe", side_effect=AssertionError("hash")), patch("insightpilot.tools.duckdb_engine.AnalyticsEngine.run_sql", side_effect=AssertionError("SQL")):
        result = advise(dataset, request)
    assert result["planning_status"] == "ready"
    assert result["analysis_advice"]["effective_method"]["method_ref"] == "playbook:metric_trend"
    assert len(result["analysis_advice"]["candidates"]) <= 3


def test_wrong_causal_returns_actual_missing_role_without_execution():
    dataset, request = prepare(question="昨日订单量为什么下降？", goal_mode="metric_diagnosis", playbook_id="causal_exploration", column_mapping={"table_name": "daily", "metric_columns": ["orders"], "outcome_column": "orders"}, playbook_parameters={"control_value": "control", "treatment_value": "treatment"})
    with patch("insightpilot.agents.workflow.execute_playbook", side_effect=AssertionError("executed")) as execute, patch("insightpilot.agents.workflow.generate_markdown_report", side_effect=AssertionError("report")) as report:
        result = run_agent_analysis(**request, tables={}, prepared_dataset=dataset, data_source_type="csv")
    assert result["execution_status"] == "NEEDS_INPUT"
    assert result["trace"]["executed_queries"] == []
    assert execute.call_count == report.call_count == 0
    codes = [item["code"] for item in result["preflight"]["blocking_issues"]]
    assert "MISSING_TREATMENT_COLUMN" in codes
    assert "MISSING_OUTCOME_COLUMN" not in codes
    assert "METHOD_GOAL_MISMATCH" in codes
    assert result["run_manifest"]["analysis_advice"]["effective_method"]["method_ref"] == "playbook:causal_exploration"


@pytest.mark.parametrize("question", ["预测未来30天订单", "证明订单下降的因果关系"])
def test_unsupported_questions_do_not_become_successful_summaries(question):
    dataset, request = prepare(question=question, playbook_id=None)
    result = advise(dataset, request)
    assert result['planning_status'] == 'unsupported'
    assert not result['analysis_advice']['can_submit']


def test_negation_and_period_comparison():
    dataset, request = prepare(question="不做因果，只比较本周上周订单量", playbook_id=None)
    result = advise(dataset, request)
    assert result['analysis_advice']['effective_method']['method_ref'] == 'playbook:period_comparison'
    assert result['planning_status'] == 'ready'


def test_missing_exact_metadata_requires_preparation():
    dataset, request = prepare()
    metadata = dataset.metadata
    metadata['daily'].pop('readiness_summary')
    result = prepare_analysis_request(**request, table_metadata=metadata)
    assert result['planning_status'] == 'needs_clarification'
    assert result['analysis_advice']['effective_method']['data_readiness'] == 'needs_preparation'


def test_numeric_group_not_named_group_can_be_explicitly_selected():
    frame = pd.DataFrame({'z': [0] * 12 + [1] * 12, 'outcome': list(range(12)) + list(range(2, 14))})
    dataset = PreparedDataset.from_tables({'sample': frame})
    request = dict(question='探索两组结果关联', goal_mode='causal_exploration', playbook_id='causal_exploration', column_mapping={'table_name': 'sample', 'treatment_column': 'z', 'outcome_column': 'outcome', 'metric_columns': ['outcome']}, playbook_parameters={'control_value': 0, 'treatment_value': 1, 'covariates': []})
    result = advise(dataset, request)
    assert result['planning_status'] == 'ready', result['preflight']
    actual = run_agent_analysis(**request, tables={}, prepared_dataset=dataset, data_source_type='csv', presentation_mode='deferred')
    assert actual['execution_status'] == 'COMPLETED'
    assert actual['result_tables']['adjusted_effect_summary'].iloc[0]['naive_difference'] == 2
    assert '未经调整' in str(result['analysis_advice']['effective_method']['necessary_caveats'])


def test_source_and_data_identity_bind_advice():
    dataset, request = prepare()
    first = advise(dataset, request)['preflight']['request_fingerprint']
    other = PreparedDataset.from_tables({'daily': daily()}, dataset_id='other', revision='r1')
    assert advise(other, request)['preflight']['request_fingerprint'] != first
    assert advise(dataset, request, selection_source='history_restored')['preflight']['request_fingerprint'] != first
    changed = copy.deepcopy(request); changed['column_mapping']['aggregation'] = 'mean'
    assert advise(dataset, changed)['preflight']['request_fingerprint'] != first
    assert advise(dataset, request)['preflight']['request_fingerprint'] == first


def test_metadata_memory_is_part_of_unchanged_budget():
    dataset, _ = prepare()
    assert dataset.estimated_bytes > daily().memory_usage(index=True, deep=True).sum()
    metadata = dataset.metadata
    metadata['daily']['readiness_summary']['columns']['orders']['valid_numeric_count'] = 0
    assert dataset.metadata['daily']['readiness_summary']['columns']['orders']['valid_numeric_count'] == 16


def test_manual_choice_never_silently_changes():
    dataset, request = prepare(question='查看数据缺失和类型', goal_mode='experiment_analysis', playbook_id='experiment_comparison')
    result = advise(dataset, request, selection_source='user_selected')
    assert result['analysis_advice']['requested_method']['id'] == 'experiment_comparison'
    assert result['analysis_advice']['effective_method']['id'] == 'experiment_comparison'
    assert result['analysis_advice']['effective_method']['goal_fit'] == 'unrelated'
    assert not result['analysis_advice']['can_submit']


def test_invalid_period_input_is_structured_not_render_exception():
    dataset, request = prepare(question='比较订单量周期', playbook_id='period_comparison', playbook_parameters={'current_start': 'not-a-date'})
    result = advise(dataset, request)
    assert not result['analysis_advice']['can_submit']
    assert 'INVALID_PARAMETER' in [item['code'] for item in result['preflight']['blocking_issues']]


def test_no_implicit_custom_causal_direction():
    frame = pd.DataFrame({'group': ['control'] * 12 + ['treatment'] * 12, 'outcome': range(24)})
    dataset, request = prepare(frame, question='轻量因果探索', goal_mode='causal_exploration', playbook_id='causal_exploration', column_mapping={'table_name': 'daily', 'treatment_column': 'group', 'outcome_column': 'outcome', 'metric_columns': ['outcome']})
    result = advise(dataset, request)
    assert not result['analysis_advice']['can_submit']
    assert {'MISSING_CONTROL_VALUE', 'MISSING_TREATMENT_VALUE'} <= {item['code'] for item in result['preflight']['blocking_issues']}


def test_distinct_text_numeric_preparation_is_exact():
    frame = pd.DataFrame({'date': pd.date_range('2026-01-01', periods=6), 'orders': ['1', ' 2.5 ', '-3e1', 'bad', 'Infinity', None]})
    dataset = PreparedDataset.from_tables({'daily': frame})
    fact = dataset.metadata['daily']['readiness_summary']['columns']['orders']
    assert fact['non_null_count'] == 5
    assert fact['valid_numeric_count'] == 3
    assert fact['binary_numeric'] is False


@pytest.mark.parametrize("mapping_extras", [{}, {"source": "user_selected"}, {"timezone": "UTC", "aggregation": "mean"}])
def test_shared_preflight_fingerprint_survives_workflow_mapping_defaults(mapping_extras):
    dataset, request = prepare(question='昨日订单量为什么下降？', goal_mode='metric_diagnosis', playbook_id='causal_exploration', column_mapping={'table_name': 'daily', 'date_column': 'date', 'metric_columns': ['orders'], 'outcome_column': 'orders', **mapping_extras}, playbook_parameters={'control_value': 'control', 'treatment_value': 'treatment'})
    expected = advise(dataset, request, selection_source='user_selected')
    actual = run_agent_analysis(**request, tables={}, prepared_dataset=dataset, data_source_type='csv', selection_source='user_selected', presentation_mode='deferred')
    assert expected['metric_definitions'] == actual['metric_definitions']
    assert expected['preflight'] == actual['preflight']
    assert '_requested_column_mapping' not in actual['workflow_state']['intermediate_results']


def _change_contribution_request(method='auto'):
    rows = [{'date': day, 'city': city, 'orders': (30 if day.day < 16 else 10) if city == 'A' else 20}
            for day in pd.date_range('2026-01-01', periods=16) for city in ('A', 'B')]
    return prepare(pd.DataFrame(rows), question='各城市对订单下降贡献了多少？', playbook_id=method,
                   column_mapping={'table_name': 'daily', 'date_column': 'date', 'metric_columns': ['orders'],
                                   'dimension_columns': ['city'], 'aggregation': 'sum'})


def test_change_contribution_auto_uses_real_period_differences():
    dataset, request = _change_contribution_request()
    prepared = advise(dataset, request, selection_source='automatic')
    assert prepared['analysis_advice']['effective_method']['method_ref'] == 'route:legacy'
    assert prepared['planning_status'] == 'ready'
    result = run_agent_analysis(**request, tables={}, prepared_dataset=dataset, data_source_type='csv',
                                selection_source='automatic', presentation_mode='deferred')
    assert result['execution_status'] == 'COMPLETED'
    assert 'dimension_contribution' not in result['result_tables']
    contribution = result['result_tables']['dimension_city'].set_index('dimension_value')
    # Last date A=10 vs seven preceding dates each 30; B remains 20.
    assert contribution.loc['A', 'current_value'] == 10
    assert contribution.loc['A', 'baseline_value'] == 30
    assert contribution.loc['A', 'change'] == -20
    assert contribution.loc['B', 'current_value'] == contribution.loc['B', 'baseline_value'] == 20
    assert contribution.loc['B', 'change'] == 0


def test_manual_static_contribution_cannot_answer_change_without_confirmation():
    dataset, request = _change_contribution_request('dimension_contribution')
    with patch('insightpilot.tools.duckdb_engine.AnalyticsEngine.run_sql', side_effect=AssertionError('SQL')), \
            patch('insightpilot.agents.workflow.execute_playbook', side_effect=AssertionError('statistics')):
        result = run_agent_analysis(**request, tables={}, prepared_dataset=dataset, data_source_type='csv',
                                    selection_source='user_selected', presentation_mode='deferred')
    assert result['execution_status'] == 'NEEDS_INPUT'
    advice = result['analysis_advice']
    assert advice['requested_method']['id'] == advice['effective_method']['id'] == 'dimension_contribution'
    assert advice['effective_method']['goal_fit'] == 'unrelated'
    assert '静态' in advice['effective_method']['reason_zh']
    assert 'METHOD_GOAL_MISMATCH' in {item['code'] for item in result['preflight']['blocking_issues']}
    assert result['trace']['executed_queries'] == []
    assert not result['result_tables']


def test_static_distribution_remains_available_with_existing_dates():
    dataset, request = _change_contribution_request()
    request['question'] = '各城市订单量构成占比是多少？'
    prepared = advise(dataset, request, selection_source='automatic')
    assert prepared['planning_status'] == 'ready'
    assert prepared['analysis_advice']['effective_method']['id'] == 'dimension_contribution'


@pytest.mark.parametrize('question', ['各渠道对订单上升的贡献是多少？', '按城市拆开订单量的变化贡献'])
def test_change_contribution_routing_is_not_a_single_question_special_case(question):
    dataset, request = _change_contribution_request()
    request['question'] = question
    prepared = advise(dataset, request, selection_source='automatic')
    assert prepared['analysis_advice']['effective_method']['method_ref'] == 'route:legacy'
