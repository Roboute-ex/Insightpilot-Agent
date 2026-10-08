"""Behavior regressions for measured P0 work; no timing thresholds."""
from copy import deepcopy
import json
from unittest.mock import Mock

import numpy as np
import pandas as pd
import pytest

from insightpilot.agents.dataset import PreparedDataset
from insightpilot.agents.state import WorkflowState
from insightpilot.agents.workflow import run_agent_analysis
from insightpilot.data.scenarios import generate_scenario
from insightpilot.data.synthetic import generate_multi_table_commerce_data
from insightpilot.observability.tracer import LocalTracer
from insightpilot.visualization.result_charts import materialize_charts


def _table():
    return pd.DataFrame({'date':pd.date_range('2026-01-01',periods=35),'sales':np.arange(35,dtype=float),'city':['A']*35})


def test_prepared_dataset_owns_inputs_public_views_and_metadata(monkeypatch):
    import insightpilot.agents.dataset as module
    original=_table()
    counted=Mock(wraps=module.fingerprint_dataframe)
    monkeypatch.setattr(module,'fingerprint_dataframe',counted)
    prepared=PreparedDataset.from_tables({'one':original,'alias':original},'dataset','1',metadata={'one':{'warnings':['读取编码为GBK']}})
    assert counted.call_count==1
    assert prepared._tables['one'] is prepared._tables['alias']
    from insightpilot.performance import estimate_size_bytes
    retained_metadata=estimate_size_bytes((prepared._metadata,prepared._fingerprints,prepared.preparation_telemetry))
    assert prepared.estimated_bytes==int(prepared._tables['one'].memory_usage(index=True,deep=True).sum())+retained_metadata
    original.loc[0,'sales']=999
    exposed=prepared.tables
    exposed['one'].loc[1,'sales']=888
    exposed['one'].loc[2,'city']='mutated'
    assert prepared.tables['one'].sales.iloc[:2].tolist()==[0.,1.]
    assert prepared.tables['one'].city.iloc[2]=='A'
    metadata=prepared.metadata;metadata['one']['warnings'].clear()
    assert '读取编码为GBK' in prepared.metadata['one']['warnings']
    assert prepared.fingerprints['one']==prepared.fingerprints['alias']
    changed=PreparedDataset.from_tables({'one':original},'dataset','2')
    assert changed.fingerprints['one']!=prepared.fingerprints['one']


def test_prepared_runs_reuse_quality_and_input_fingerprints(monkeypatch):
    import insightpilot.agents.workflow as workflow
    prepared=PreparedDataset.from_tables({'custom':_table()},'dataset','1')
    fingerprint=workflow.fingerprint_dataframe
    checked=[]
    def count(frame):
        checked.append(id(frame));return fingerprint(frame)
    monkeypatch.setattr(workflow,'fingerprint_dataframe',count)
    monkeypatch.setattr(workflow,'validate_tables_for_workflow',Mock(side_effect=AssertionError('quality repeated')))
    monkeypatch.setattr(workflow,'infer_schema_mapping',Mock(side_effect=AssertionError('schema repeated')))
    kwargs=dict(question='趋势',tables={},prepared_dataset=prepared,presentation_mode='deferred',data_source_type='uploaded_files',goal_mode='growth_trend',column_mapping={'table_name':'custom','date_column':'date','metric_columns':['sales'],'dimension_columns':['city']})
    first=run_agent_analysis(**kwargs);second=run_agent_analysis(**kwargs)
    pd.testing.assert_frame_equal(first['result_tables']['metric_trend'],second['result_tables']['metric_trend'])
    assert id(prepared._tables['custom']) not in checked
    assert first['telemetry']['summary']['query_count']==0
    assert first['workflow_state']['dataset_revision']=='1'


def test_direct_run_fingerprints_each_input_once_and_keeps_eager_contract(monkeypatch):
    import insightpilot.agents.workflow as workflow
    tables=generate_scenario('transaction',scale='small',seed=42).tables
    counts={id(frame):0 for frame in tables.values()};fingerprint=workflow.fingerprint_dataframe
    def count(frame):
        if id(frame) in counts:counts[id(frame)]+=1
        return fingerprint(frame)
    monkeypatch.setattr(workflow,'fingerprint_dataframe',count)
    result=run_agent_analysis('昨日订单量为什么下降？',tables,goal_mode='metric_diagnosis')
    assert all(count==1 for count in counts.values())
    assert result['charts'] and result['report_markdown']
    assert result['telemetry']['summary']['query_count']==1
    names={span['name'] for span in result['telemetry']['spans']}
    assert {'generate_report','review','build_manifest','table_registration','sql_query','statistics_result_package'}.issubset(names)
    total=sum(span['duration_ms'] for span in result['telemetry']['spans'] if span['parent_span_id'] is None)
    assert result['telemetry']['summary']['total_duration_ms']==pytest.approx(total,abs=.001)


def test_deferred_skips_presentation_and_selected_materialization_is_read_only(monkeypatch):
    import insightpilot.agents.workflow as workflow
    import insightpilot.visualization.factory as factory
    tables=generate_scenario('transaction',scale='small',seed=42).tables
    eager=run_agent_analysis('昨日订单量为什么下降？',tables,goal_mode='metric_diagnosis')
    monkeypatch.setattr(workflow,'build_charts',Mock(side_effect=AssertionError('unexpected charts')))
    monkeypatch.setattr(workflow,'generate_markdown_report',Mock(side_effect=AssertionError('unexpected markdown')))
    deferred=run_agent_analysis('昨日订单量为什么下降？',tables,goal_mode='metric_diagnosis',presentation_mode='deferred')
    assert deferred['charts']==[] and deferred['report_markdown']=='' and deferred['chart_specs']
    for key,frame in eager['result_tables'].items():pd.testing.assert_frame_equal(frame,deferred['result_tables'][key])
    original=deepcopy(deferred['chart_specs'])
    counted=Mock(wraps=factory.build_chart);monkeypatch.setattr(factory,'build_chart',counted)
    pairs=materialize_charts(deferred,[original[0]['chart_id']],max_points=100)
    assert len(pairs)==1 and counted.call_count==1
    assert deferred['chart_specs']==original
    assert deferred['charts']==[]


def test_state_summary_never_deepcopies_dataframe(monkeypatch):
    state=WorkflowState(intermediate_results={'large':_table()})
    monkeypatch.setattr(pd.DataFrame,'__deepcopy__',Mock(side_effect=AssertionError('unnecessary copy')))
    payload=state.to_dict()
    assert payload['intermediate_results']['large']['row_count']==35
    assert 'sales' in json.dumps(payload)
    assert 'data' not in payload['intermediate_results']['large']


def test_no_sql_path_never_opens_connection_and_reports_operation_separately(monkeypatch):
    import insightpilot.tools.duckdb_engine as tools
    tables=generate_scenario('content',scale='small',seed=42).tables
    monkeypatch.setattr(tools.duckdb,'connect',Mock(side_effect=AssertionError('unused connection')))
    result=run_agent_analysis('新策略是否提升完播率？',tables,goal_mode='experiment_analysis',presentation_mode='deferred')
    assert result['execution_status']=='COMPLETED'
    assert result['telemetry']['summary']['query_count']==0
    assert result['telemetry']['summary']['operation_count']==1


def test_workflow_closes_actual_connection_after_late_failure(monkeypatch):
    import insightpilot.agents.workflow as workflow
    from insightpilot.tools.duckdb_engine import AnalyticsEngine
    tables=generate_scenario('transaction',scale='small',seed=42).tables
    closed=[];close=AnalyticsEngine.close
    def tracked(engine):closed.append(engine);close(engine)
    monkeypatch.setattr(AnalyticsEngine,'close',tracked)
    monkeypatch.setattr(workflow,'_report_node',Mock(side_effect=RuntimeError('late report failure')))
    with pytest.raises(RuntimeError,match='late report failure'):
        run_agent_analysis('订单量',tables,goal_mode='metric_diagnosis',presentation_mode='deferred')
    assert len(closed)==1


def test_semantic_compilation_shares_exact_hash_but_execution_rechecks(monkeypatch):
    import insightpilot.semantic.compiler as module
    from insightpilot.semantic.catalog import load_builtin_catalog
    from insightpilot.semantic.query import MetricRequest
    tables=generate_multi_table_commerce_data()
    counted=Mock(wraps=module.data_fingerprint);monkeypatch.setattr(module,'data_fingerprint',counted)
    compiler=module.MetricCompiler(load_builtin_catalog().get('commerce_demo'))
    plan=compiler.compile(MetricRequest(metrics=['total_revenue','session_count','revenue_per_session'],dimensions=['customer_city']),tables=tables)
    assert counted.call_count==1
    tables['orders'].loc[0,'total_amount']+=1
    assert module.execute_query_plan(plan,tables)[1].decision=='rejected'
    assert counted.call_count==2


def test_nested_spans_do_not_double_count():
    tracer=LocalTracer()
    with tracer.span('parent'):
        with tracer.span('child'):
            sum(range(1000))
    assert tracer.spans[1].parent_span_id==tracer.spans[0].span_id
    assert tracer.summary().total_duration_ms==tracer.spans[0].duration_ms


def test_display_sampling_preserves_marked_anomaly_without_changing_statistics():
    frame=pd.DataFrame({'date':pd.date_range('2020-01-01',periods=1000),'value':np.sin(np.arange(1000)),'is_anomaly':[i==557 for i in range(1000)]})
    frame.loc[557,'value']=999
    result={'chart_specs':[{'chart_id':'trend','chart_type':'time_series','title':'趋势','table_key':'trend','x':'date','y':['value']}],'result_tables':{'trend':frame}}
    original=frame.copy(deep=True)
    spec,figure=materialize_charts(result,max_points=40)[0]
    assert sum(len(trace.x) for trace in figure.data)<=40
    assert 999 in figure.data[0].y
    assert '完整统计未抽样' in spec.metadata['display_note']
    pd.testing.assert_frame_equal(frame,original)


def test_anomaly_budget_rejection_has_explicit_warning_and_preserves_inputs():
    frame=pd.DataFrame({'date':pd.date_range('2026-01-01',periods=30),'value':range(30),'is_anomaly':[True]*30})
    result={'chart_specs':[{'chart_id':'overflow','chart_type':'time_series','title':'趋势','table_key':'trend','x':'date','y':['value']}],'result_tables':{'trend':frame}}
    original=frame.copy(deep=True)
    original_specs=deepcopy(result['chart_specs'])
    charts=materialize_charts(result,max_points=10)
    assert charts == []
    assert isinstance(charts.warnings,tuple)
    assert len(charts.warnings)==1
    assert 'overflow' in charts.warnings[0] and '异常点超过当前绘图预算' in charts.warnings[0]
    assert '未删除统计样本' in charts.warnings[0]
    with pytest.raises(AttributeError):
        charts.warnings=()
    pd.testing.assert_frame_equal(frame,original)
    assert result['chart_specs']==original_specs
