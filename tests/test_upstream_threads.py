from copy import deepcopy
from dataclasses import replace
import json
import pytest
from app.session_data import AnalysisSession
from insightpilot.analysis.threads import AnalysisThread, compare_runs, validate_history_json
from insightpilot.performance import PerformanceConfig, MemoryBudgetExceeded


def outcome(run, value=.2, *, unit='比例', version='1', metric='cvr'):
    return {'execution_status':'COMPLETED', 'goal_mode':'metric_diagnosis',
        'run_manifest':{'run_id':run,'created_at':'2026-09-23T00:00:00Z'},
        'metric_definitions':[{'metric_id':metric,'definition_version':version,'unit':unit,
            'numerator':'paid','denominator':'visitors','aggregation':'ratio','statistical_unit':'journey',
            'timezone':'Asia/Shanghai','date_column':'date','zero_denominator_policy':'undefined',
            'scope':'t','expression':'sum(paid)/sum(visitors)','deduplication_key':None,'null_policy':'exclude_invalid_numeric'}],
        'column_mapping':{'date_column':'date','timezone':'Asia/Shanghai','dimension_columns':['city'],'aggregation':'ratio'},
        'analysis_result_package':{'metric_comparisons':[{'metric_id':metric,'current_value':value,
            'unit':unit,'baseline_period':'前 7 日均值','current_period':'2026-09-01'}],'evidence':[{'evidence_id':'E-1'}]},
        'result_tables':{}}


def add(history, run, value=.2, config=None, **kwargs):
    return history.add(outcome(run,value,**kwargs),config or {'question':'转化率','parameters':{}},
        dataset_id='same-data',revision='1',schema={'t':['date','paid','visitors','city']})


def test_immutable_history_contains_no_result_objects_and_is_bounded():
    thread=AnalysisThread(max_nodes=3)
    result=outcome('r1');config={'question':'转化率','parameters':{'filters':[{'column':'city','value':'甲'}]}}
    node=thread.add(result,config,dataset_id='same-data',revision='1',schema={'t':['date']})
    config['parameters']['filters'][0]['value']='乙';result['metric_definitions'][0]['unit']='元'
    assert node.config['parameters']['filters'][0]['value']=='甲'
    assert node.context['definitions'][0]['unit']=='比例'
    changed=node.config;changed['question']='other';assert node.config['question']=='转化率'
    for i in range(2,7):add(thread,f'r{i}')
    assert len(thread.nodes)==3 and thread.size_bytes<=thread.max_bytes
    assert all(isinstance(n.result_ref,str) and isinstance(n.result_summary,str) for n in thread.nodes)
    with pytest.raises(ValueError):thread.get(node.node_id)


def test_ratio_differences_are_percentage_points_not_significance():
    thread=AnalysisThread();a=add(thread,'a',.2);b=add(thread,'b',.25)
    compared=compare_runs(a,b)
    assert compared['status']=='comparable'
    assert compared['rows'][0]['absolute_change']==pytest.approx(5)
    assert compared['rows'][0]['relative_change']==pytest.approx(.25)
    assert compared['rows'][0]['unit']=='百分点'
    assert '不是显著性检验' in compared['rows'][0]['note']


def test_unit_definition_dimension_and_filters_changes_refuse_comparison():
    thread=AnalysisThread();a=add(thread,'a')
    for kwargs in ({'unit':'元'},{'version':'2'}):
        b=add(thread,str(kwargs),**kwargs);assert compare_runs(a,b)['status']=='not_comparable'
    raw=outcome('dim');raw['column_mapping']['dimension_columns']=['channel']
    b=thread.add(raw,{},dataset_id='same-data',revision='1',schema={'t':['date','paid','visitors','city']})
    assert compare_runs(a,b)['status']=='not_comparable'
    b=add(thread,'filter',config={'parameters':{'filters':[{'column':'city','value':'上海'}]}})
    assert compare_runs(a,b)['status']=='not_comparable'


def test_changed_window_is_context_differs_and_zero_relative_is_undefined():
    thread=AnalysisThread();a=add(thread,'a',0,{'parameters':{'current_start':'2026-01-01'}})
    b=add(thread,'b',.2,{'parameters':{'current_start':'2026-02-01'}})
    result=compare_runs(a,b)
    assert result['status']=='context_differs'
    assert result['rows'][0]['relative_change'] is None
    assert '时间窗口' in result['rows'][0]['note']


def test_groups_align_by_keys_and_missing_values_are_not_zero_filled():
    thread=AnalysisThread();a=add(thread,'a');b=add(thread,'b')
    def groups(node,rows):
        summary=node.summary;summary['rows']=rows
        return replace(node,result_summary=json.dumps(summary))
    a=groups(a,[{'metric_id':'cvr','value':.2,'group':{'city':'甲'}},{'metric_id':'cvr','value':.4,'group':{'city':'乙'}}])
    b=groups(b,[{'metric_id':'cvr','value':.5,'group':{'city':'乙'}},{'metric_id':'cvr','value':.8,'group':{'city':'丙'}}])
    rows=compare_runs(a,b)['rows'];by_city={r['group']['city']:r for r in rows}
    assert by_city['乙']['absolute_change']==pytest.approx(10)
    assert by_city['甲']['run_b'] is None and by_city['甲']['absolute_change'] is None
    assert by_city['丙']['run_a'] is None


def test_duplicate_summary_keys_refused_not_positional():
    thread=AnalysisThread();a=add(thread,'a');b=add(thread,'b')
    summary=a.summary;summary['rows']*=2;a=replace(a,result_summary=json.dumps(summary))
    assert compare_runs(a,b)['status']=='not_comparable'


def test_old_task_and_cross_session_references_cannot_be_adopted():
    first=AnalysisThread();node=add(first,'a');second=AnalysisThread();other=add(second,'b')
    assert compare_runs(node,other)['status']=='not_comparable'
    with pytest.raises(ValueError):second.select(node.node_id)
    old=first.begin_request(node.run_id);first.begin_request(node.run_id)
    with pytest.raises(ValueError,match='旧任务'):
        first.add(outcome('late'),{},dataset_id='same-data',revision='1',schema={},node_id=old)
    first.bind_dataset('same-data','2')
    assert not first.nodes and not first.result_available(node,outcome('a'))


def test_result_release_preserves_summary_but_not_a_fake_result():
    session=AnalysisSession();result=outcome('a');session.accept('key',result)
    node=add(session.history,'a');assert session.history.result_available(node,session.current)
    session.clear()
    assert node.summary['rows'] and not session.history.result_available(node,session.current)
    assert session.cache.max_entries==1
    assert session.cache.max_bytes+session.history.max_bytes==PerformanceConfig().result_max_bytes


def test_history_export_redacts_inputs_and_import_is_validation_only():
    thread=AnalysisThread();add(thread,'a',config={'question':'收入，路径D:/private/data.csv',
        'parameters':{'filters':[{'column':'city','value':'秘密城市'}],'control_value':'secret-group'},
        'column_mapping':{'original_request':{'database_url':'sqlite:///secret.db'}}})
    content=thread.export_json();parsed=validate_history_json(content)
    assert '秘密城市' not in content and 'secret-group' not in content and 'private' not in content and 'secret.db' not in content
    assert parsed['nodes'][0]['requires_input'] is True
    assert parsed['nodes'][0]['config']['question']=={'requires_input':True}
    bad=json.loads(content);bad['nodes'][0]['parent_run_id']='a'
    with pytest.raises(ValueError):validate_history_json(json.dumps(bad))
    with pytest.raises(ValueError):validate_history_json('{"schema_version":"1.0","schema_version":"1.0","nodes":[]}')
    with pytest.raises(ValueError):validate_history_json(' '* (512*1024+1))
    with pytest.raises(ValueError):validate_history_json('{"schema_version":"99","nodes":[]}')


def test_history_over_budget_rejects_metadata_without_truncating_result():
    thread=AnalysisThread(max_bytes=32)
    with pytest.raises(MemoryBudgetExceeded):add(thread,'a')
    assert thread.nodes==[]


def test_auto_branches_compare_frozen_effective_methods_not_request_sentinels():
    thread = AnalysisThread()
    config = {"playbook_id": "auto", "effective_playbook_id": "metric_trend"}
    left = add(thread, "auto-trend", .2, config)
    config["effective_playbook_id"] = "period_comparison"
    right = add(thread, "auto-period", .25, config)
    assert left.config["playbook_id"] == right.config["playbook_id"] == "auto"
    assert left.context["method"]["playbook"] == "metric_trend"
    assert right.context["method"]["playbook"] == "period_comparison"
    compared = compare_runs(left, right)
    assert compared["status"] == "not_comparable"
    assert compared["rows"] == []
    assert "统计方法不同，不直接相减。" in compared["reasons"]


@pytest.mark.parametrize("other_config", [
    {"playbook_id": "auto", "effective_playbook_id": "metric_trend"},
    {"playbook_id": "auto_recommended", "effective_playbook_id": "metric_trend"},
    {"playbook_id": "metric_trend"},
])
def test_same_effective_method_keeps_auto_and_explicit_results_comparable(other_config):
    thread = AnalysisThread()
    left = add(thread, "auto", .2, {"playbook_id": "auto", "effective_playbook_id": "metric_trend"})
    right = add(thread, "same-method", .25, other_config)
    compared = compare_runs(left, right)
    assert compared["status"] == "comparable"
    assert compared["rows"][0]["absolute_change"] == pytest.approx(5)
    assert compared["rows"][0]["unit"] == "百分点"


@pytest.mark.parametrize("legacy_config", [{}, {"playbook_id": None}, {"playbook_id": "__legacy__"}])
def test_auto_legacy_route_is_compatible_with_old_legacy_history(legacy_config):
    thread = AnalysisThread()
    left = add(thread, "auto-legacy", .2, {"playbook_id": "auto", "effective_playbook_id": None})
    right = add(thread, "old-legacy", .25, legacy_config)
    assert left.context["method"]["playbook"] is None
    assert right.context["method"]["playbook"] is None
    assert compare_runs(left, right)["status"] == "comparable"


@pytest.mark.parametrize("location", ["result", "manifest"])
def test_frozen_result_advice_resolves_auto_history_without_config_effective_method(location):
    thread = AnalysisThread()
    result = outcome("advised", .2)
    advice = {"effective_method": {"kind": "playbook", "id": "metric_trend"}}
    target = result if location == "result" else result["run_manifest"]
    target["analysis_advice"] = advice
    left = thread.add(result, {"playbook_id": "auto"}, dataset_id="same-data", revision="1",
                      schema={"t": ["date", "paid", "visitors", "city"]})
    advice["effective_method"]["id"] = "period_comparison"
    right = add(thread, "explicit", .25, {"playbook_id": "metric_trend"})
    assert left.context["method"]["playbook"] == "metric_trend"
    assert compare_runs(left, right)["status"] == "comparable"


def test_successful_result_advice_takes_priority_over_conflicting_frozen_config():
    thread = AnalysisThread()
    result = outcome("executed")
    result["analysis_advice"] = {"effective_method": {"kind": "playbook", "id": "metric_trend"}}
    left = thread.add(result, {"playbook_id": "auto", "effective_playbook_id": None},
                      dataset_id="same-data", revision="1", schema={"t": ["date", "paid", "visitors", "city"]})
    right = add(thread, "trend", .25, {"playbook_id": "metric_trend"})
    assert left.context["method"]["playbook"] == "metric_trend"
    assert compare_runs(left, right)["status"] == "comparable"


def test_successful_selected_playbook_takes_priority_over_request_and_advice():
    thread = AnalysisThread()
    result = outcome("executed")
    result["selected_playbook"] = {"playbook_id": "period_comparison"}
    result["analysis_advice"] = {"effective_method": {"kind": "playbook", "id": "metric_trend"}}
    left = thread.add(result, {"playbook_id": "auto", "effective_playbook_id": "metric_trend"},
                      dataset_id="same-data", revision="1", schema={"t": ["date", "paid", "visitors", "city"]})
    right = add(thread, "trend", .25, {"playbook_id": "metric_trend"})
    assert left.context["method"]["playbook"] == "period_comparison"
    assert compare_runs(left, right)["status"] == "not_comparable"
    assert compare_runs(left, right)["rows"] == []


def test_successful_legacy_route_advice_is_not_replaced_by_request_playbook():
    thread = AnalysisThread()
    result = outcome("executed-legacy")
    result["selected_playbook"] = None
    result["analysis_advice"] = {"effective_method": {"kind": "route", "id": "legacy"}}
    left = thread.add(result, {"playbook_id": "auto", "effective_playbook_id": "metric_trend"},
                      dataset_id="same-data", revision="1", schema={"t": ["date", "paid", "visitors", "city"]})
    right = add(thread, "legacy", .25, {"playbook_id": "__legacy__"})
    assert left.context["method"]["playbook"] is None
    assert compare_runs(left, right)["status"] == "comparable"


def test_unsuccessful_result_does_not_certify_an_executed_auto_method():
    thread = AnalysisThread()
    result = outcome("incomplete")
    result["execution_status"] = "NEEDS_INPUT"
    result["selected_playbook"] = {"playbook_id": "metric_trend"}
    result["analysis_advice"] = {"effective_method": {"kind": "playbook", "id": "metric_trend"}}
    left = thread.add(result, {"playbook_id": "auto"}, dataset_id="same-data", revision="1",
                      schema={"t": ["date", "paid", "visitors", "city"]})
    right = add(thread, "trend", .25, {"playbook_id": "metric_trend"})
    assert left.context["method"]["playbook"] == "auto"
    assert compare_runs(left, right)["status"] == "not_comparable"
    assert compare_runs(left, right)["rows"] == []


@pytest.mark.parametrize("executed", [None, "period_comparison"])
def test_older_successful_manifest_method_is_authoritative(executed):
    thread = AnalysisThread()
    result = outcome("manifest")
    result["run_manifest"]["playbook_id"] = executed
    left = thread.add(result, {"playbook_id": "auto", "effective_playbook_id": "metric_trend"},
                      dataset_id="same-data", revision="1", schema={"t": ["date", "paid", "visitors", "city"]})
    assert left.context["method"]["playbook"] == executed


@pytest.mark.parametrize("requested", ["auto", "auto_recommended"])
def test_unrecorded_auto_methods_are_not_assumed_comparable(requested):
    thread = AnalysisThread()
    left = add(thread, "missing-a", .2, {"playbook_id": requested})
    right = add(thread, "missing-b", .25, {"playbook_id": requested})
    compared = compare_runs(left, right)
    assert compared["status"] == "not_comparable"
    assert compared["rows"] == []
    assert any("未记录自动推荐后实际执行的分析方法" in reason for reason in compared["reasons"])
