from collections import Counter
from pathlib import Path
from copy import deepcopy
import pandas as pd
from streamlit.testing.v1 import AppTest
from app.components.metric_definition_panel import refresh_result_presentation
from insightpilot.metrics.definitions import finalize_card, stable_fingerprint
from insightpilot.analysis.threads import compare_runs


def start(source='synthetic'):
    app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app/ui_streamlit.py'),default_timeout=90)
    app.session_state['demo_scale']='small'
    app.session_state['data_source_selector']=source
    app.run()
    assert not app.exception
    return app


def click(app,label):
    next(b for b in app.button if b.label==label).click().run()
    assert not app.exception


def watch(monkeypatch):
    import insightpilot.agents.workflow as workflow
    import app.components.export_panel as exports
    count=Counter()
    for module,name in [(workflow,'run_agent_analysis'),(exports,'prepare_export_payload')]:
        original=getattr(module,name)
        def call(*args,_fn=original,_name=name,**kwargs):
            count[_name]+=1
            return _fn(*args,**kwargs)
        monkeypatch.setattr(module,name,call)
    return count


def test_explicit_clarification_then_execute_no_automatic_confirmation(monkeypatch):
    counts=watch(monkeypatch)
    app=start('upload')
    data=b'date,gross_revenue,net_revenue,city\n2026-01-01,100,80,a\n2026-01-02,120,90,b\n'
    app.file_uploader[0].set_value(('sales.csv',data,'text/csv')).run()
    app.text_input(key='question').set_value('收入是多少？').run()
    select=next(s for s in app.selectbox if str(s.key).startswith('clarification_'))
    assert select.value is None
    assert app.button(key='guided_run').disabled
    assert counts['run_agent_analysis']==0
    select=next(s for s in app.selectbox if str(s.key).startswith('clarification_'))
    select.set_value('sales:net_revenue').run()
    click(app,'确认口径选择')
    assert counts['run_agent_analysis']==0
    click(app,'开始分析')
    result=app.session_state['last_analysis_result']
    assert result['execution_status']=='COMPLETED'
    assert result['metric_definitions'][0]['metric_id']=='net_revenue'
    assert counts['run_agent_analysis']==1
    assert counts['prepare_export_payload']==0


def test_branch_back_key_comparison_and_selected_run_export(monkeypatch):
    counts=watch(monkeypatch);app=start();click(app,'开始分析')
    app.segmented_control(key='workbench_page').set_value('history').run()
    history=app.session_state['performance_result'].history
    parent=history.nodes[-1]
    app.toggle(key='history_details').set_value(True).run()
    app.selectbox(key='history_dimension').set_value('city').run()
    click(app,'修改维度重新分析')
    assert counts['run_agent_analysis']==1
    click(app,'开始分析'); city=history.nodes[-1]
    assert city.parent_run_id==parent.run_id
    app.segmented_control(key='workbench_page').set_value('history').run()
    click(app,'返回上一步')
    assert history.active_node_id==parent.node_id
    assert any('结果已释放' in i.value for i in app.info)
    assert counts['run_agent_analysis']==2
    app.segmented_control(key='workbench_page').set_value('history').run()
    if not app.toggle(key='history_details').value:
        app.toggle(key='history_details').set_value(True).run()
    app.selectbox(key='history_dimension').set_value('channel').run()
    click(app,'修改维度重新分析');click(app,'开始分析')
    channel=history.nodes[-1]
    assert channel.parent_run_id==parent.run_id
    assert compare_runs(city,channel)['status']=='not_comparable'
    app.segmented_control(key='workbench_page').set_value('history').run()
    if not app.toggle(key='history_details').value:
        app.toggle(key='history_details').set_value(True).run()
    app.selectbox(key='history_compare_target').set_value(city.node_id).run()
    assert counts['run_agent_analysis']==3
    assert counts['prepare_export_payload']==0
    app.session_state['requested_result_tab']='报告导出';app.run()
    assert counts['prepare_export_payload']==0
    # Unsubmitted editing cannot change the selected run export identity.
    app.segmented_control(key='workbench_page').set_value('workbench').run()
    app.text_input(key='question').set_value('尚未提交的新问题').run()
    for label in ('生成 PDF 报告','生成 Excel 报告','生成 ZIP 报告包'):
        click(app,label)
    cache=app.session_state['performance_export_cache']
    assert app.session_state['export_run_id']==channel.run_id
    from app.components.export_panel import export_cache_key
    import json
    result=app.session_state['last_analysis_result']
    payload=cache.get(export_cache_key(result,'manifest'))
    assert json.loads(payload)['run_id']==channel.run_id
    assert cache.get(export_cache_key(result,'pdf')).startswith(b'%PDF')
    assert counts['run_agent_analysis']==3


def test_presentation_refresh_shares_data_and_preserves_calculation():
    frame=pd.DataFrame({'value':[1,2]})
    old=finalize_card({'metric_id':'orders','display_name':'订单量','unit':'单','expression':'sum(orders)'})
    new=finalize_card({**old,'display_name':'有效订单量'})
    result={'semantic_fingerprint':'same','presentation_fingerprint':'old','metric_definitions':[old],
            'run_manifest':{'run_id':'fixed','semantic_fingerprint':'same'},'result_tables':{'table':frame}}
    updated=refresh_result_presentation(result,{'semantic_fingerprint':'same','presentation_fingerprint':'new','metric_definitions':[new]})
    assert updated['result_tables']['table'] is frame
    assert result['metric_definitions'][0]['display_name']=='订单量'
    assert updated['run_manifest']['metric_definitions'][0]['display_name']=='有效订单量'
    assert updated['run_manifest']['run_id']=='fixed'
    changed=finalize_card({**new,'unit':'元'})
    assert refresh_result_presentation(result,{'semantic_fingerprint':'same','presentation_fingerprint':'new','metric_definitions':[changed]}) is result


def test_multiple_conversion_definitions_click_to_confirm(monkeypatch):
    counts=watch(monkeypatch);app=start('upload')
    from insightpilot.evaluation.task_suite import daily_fixture
    app.file_uploader[0].set_value(('daily.csv',daily_fixture().to_csv(index=False).encode(),'text/csv')).run()
    app.text_input(key='question').set_value('转化率为什么下降？').run()
    assert next(s for s in app.selectbox if str(s.key).startswith('clarification_')).value is None
    assert app.button(key='guided_run').disabled;assert counts['run_agent_analysis']==0
    choose=next(s for s in app.selectbox if str(s.key).startswith('clarification_') and str(s.key).endswith('_metric'))
    choose.set_value('daily:cvr').run();click(app,'确认口径选择')
    assert counts['run_agent_analysis']==0
    click(app,'开始分析'); result=app.session_state['last_analysis_result']
    assert result['execution_status']=='COMPLETED'
    card=result['metric_definitions'][0]
    assert (card['metric_id'],card['numerator'],card['denominator'])==('cvr','orders','visitors')
    assert counts['prepare_export_payload']==0


def test_window_branches_generate_descriptive_differences_without_view_analysis(monkeypatch):
    from datetime import date
    counts=watch(monkeypatch);app=start();click(app,'开始分析')
    app.segmented_control(key='workbench_page').set_value('history').run()
    history=app.session_state['performance_result'].history
    # Source end dates come from the actual bounded metadata, not new data scans.
    snapshot=app.session_state['performance_dataset'].current
    end=max(snapshot.tables['daily_metrics']['date']).date()
    from datetime import timedelta
    app.toggle(key='history_details').set_value(True).run()
    app.date_input(key='history_current_end').set_value(end)
    app.date_input(key='history_baseline_end').set_value(end-timedelta(days=7)).run()
    click(app,'修改对比基准');assert counts['run_agent_analysis']==1
    click(app,'开始分析'); first=history.nodes[-1]
    app.segmented_control(key='workbench_page').set_value('history').run()
    if not app.toggle(key='history_details').value: app.toggle(key='history_details').set_value(True).run()
    app.date_input(key='history_current_end').set_value(end-timedelta(days=1))
    app.date_input(key='history_baseline_end').set_value(end-timedelta(days=8)).run()
    click(app,'修改对比基准');click(app,'开始分析');second=history.nodes[-1]
    compared=compare_runs(first,second)
    assert compared['status']=='context_differs',compared
    assert compared['rows'] and compared['rows'][0]['unit']=='单'
    before=counts.copy()
    app.segmented_control(key='workbench_page').set_value('history').run()
    if not app.toggle(key='history_details').value: app.toggle(key='history_details').set_value(True).run()
    app.selectbox(key='history_compare_target').set_value(first.node_id).run()
    assert counts==before
