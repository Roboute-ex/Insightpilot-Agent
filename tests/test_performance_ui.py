from __future__ import annotations
from collections import Counter
from dataclasses import replace
from io import BytesIO
from pathlib import Path
import functools
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest
from ui_session_support import session_snapshot
from app.session_data import AnalysisSession, DatasetSession, analysis_cache_key
from insightpilot.performance import PerformanceConfig, MemoryBudgetExceeded

APP = Path(__file__).resolve().parents[1] / 'app/ui_streamlit.py'

def app_small(source='synthetic'):
    app = AppTest.from_file(str(APP), default_timeout=90)
    app.session_state['demo_scale'] = 'small'
    app.session_state['data_source_selector'] = source
    return app.run()

def click(app, label):
    next(x for x in app.button if x.label == label).click().run()
    assert not app.exception

def navigate(app, label):
    app.session_state['requested_result_tab'] = label
    app.run()
    assert not app.exception
    assert app.session_state['result_tabs'] == label

def counted(monkeypatch, module, name, counter, label=None):
    original = getattr(module, name)
    @functools.wraps(original)
    def wrapper(*args, **kwargs):
        counter[label or name] += 1
        return original(*args, **kwargs)
    monkeypatch.setattr(module, name, wrapper)

def test_display_reruns_do_not_reload_profile_hash_or_analyze(monkeypatch):
    import app.components.data_source_panel as source
    import insightpilot.agents.dataset as dataset
    import insightpilot.agents.workflow as workflow
    import insightpilot.visualization.result_charts as charts
    counts = Counter()
    for module, name in ((source,'load_synthetic_tables'), (dataset,'infer_schema_mapping'),
                         (dataset,'fingerprint_dataframe'), (workflow,'run_agent_analysis'), (charts,'materialize_charts')):
        counted(monkeypatch, module, name, counts)
    app = app_small()
    assert counts['load_synthetic_tables'] == 1
    assert counts['fingerprint_dataframe'] == 6
    snapshot = app.session_state['performance_dataset'].current
    original_frame = snapshot.tables['orders']
    click(app,'开始分析')
    run_id = app.session_state['last_analysis_result']['run_manifest']['run_id']
    assert 1 <= len(app.get('plotly_chart')) <= 2  # Visible overview key charts are intentional.
    assert len(app.dataframe) == 2  # Bounded result preview + city selection table; no raw preview.
    assert counts['materialize_charts'] == 1
    before = counts.copy()
    for opened in (True, False, True):
        app.session_state['guided_advanced'] = opened
        app.run()
        assert not app.exception
        assert len(app.json) == 0
    navigate(app,'结果明细')
    app.session_state['guided_quality'] = True; app.run()
    app.session_state['guided_quality'] = False; app.run()
    navigate(app,'报告导出')
    navigate(app,'分析概览')
    assert counts == before
    assert app.session_state['performance_dataset'].current.tables['orders'] is original_frame
    assert app.session_state['last_analysis_result']['run_manifest']['run_id'] == run_id
    click(app,'开始分析')
    assert counts == before
    assert app.session_state['performance_analysis_cache_hit'] is True
    app.session_state['guided_advanced'] = True; app.run()
    app.checkbox(key='force_recompute').set_value(True)
    click(app,'开始分析')
    assert counts['run_agent_analysis'] == before['run_agent_analysis'] + 1
    assert counts['fingerprint_dataframe'] == before['fingerprint_dataframe']
    assert app.session_state['last_analysis_result']['run_manifest']['run_id'] != run_id


def test_csv_upload_is_once_per_identity_and_parsing_configuration(monkeypatch):
    import app.components.data_source_panel as source
    counts = Counter()
    counted(monkeypatch,source,'read_csv_file',counts)
    app=app_small('upload')
    first=b'date,metric,city\n2026-01-01,1,a\n2026-01-02,2,b\n'
    app.file_uploader[0].set_value(('same.csv',first,'text/csv')).run()
    assert not app.exception
    original=app.session_state['performance_dataset'].current
    for opened in (True, False, True):
        app.session_state['guided_advanced'] = opened
        app.run()
    assert counts['read_csv_file']==1
    # Explicitly accept the fixture metric; timing assertions still cover the same upload.
    app.session_state['guided_advanced'] = True
    app.session_state['guided_mapping_open'] = True; app.run()
    click(app,'确认当前字段映射')
    click(app,'开始分析')
    navigate(app,'结果明细')
    assert counts['read_csv_file']==1
    changed=first.replace(b',1,',b',9,')
    assert len(changed)==len(first)
    app.file_uploader[0].set_value(('same.csv',changed,'text/csv')).run()
    assert counts['read_csv_file']==2
    assert app.session_state['performance_dataset'].current.revision!=original.revision
    assert any('上次运行结果' in str(x.value) for x in app.warning)
    app.selectbox(key='upload_encoding_0').set_value('utf-8').run()
    assert counts['read_csv_file']==3
    app.selectbox(key='upload_separator_0').set_value('分号').run()
    assert counts['read_csv_file']==4


def test_excel_sheet_list_and_selected_sheet_are_reused(monkeypatch):
    import app.components.data_source_panel as source
    counts=Counter()
    for name in ('get_excel_sheet_names','read_excel_file'):
        counted(monkeypatch,source,name,counts)
    book=BytesIO()
    with pd.ExcelWriter(book,engine='openpyxl') as writer:
        pd.DataFrame({'date':['2026-01-01'],'metric':[1]}).to_excel(writer,sheet_name='甲',index=False)
        pd.DataFrame({'date':['2026-01-01'],'metric':[9]}).to_excel(writer,sheet_name='乙',index=False)
    app=app_small('upload')
    app.file_uploader[0].set_value(('same.xlsx',book.getvalue(),'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')).run()
    revision=app.session_state['performance_dataset'].current.revision
    for opened in (True, False, True):
        app.session_state['guided_advanced'] = opened
        app.run()
    assert counts=={'get_excel_sheet_names':1,'read_excel_file':1}
    next(x for x in app.multiselect if '选择工作表' in x.label).set_value(['乙']).run()
    assert counts=={'get_excel_sheet_names':1,'read_excel_file':2}
    assert app.session_state['performance_dataset'].current.revision!=revision
    assert next(iter(app.session_state['performance_dataset'].current.tables.values()))['metric'].iloc[0]==9


def test_chart_page_builds_only_selected_chart_and_reuses_it(monkeypatch):
    import insightpilot.visualization.result_charts as charts
    counts=Counter()
    counted(monkeypatch,charts,'materialize_charts',counts)
    app=app_small(); click(app,'开始分析')
    assert counts['materialize_charts']==1
    navigate(app,'可视化诊断')
    assert counts['materialize_charts']==2
    assert len(app.get('plotly_chart'))==1
    selected=app.selectbox(key='result_chart_selector')
    values=list(app.session_state['last_analysis_result']['chart_specs'])
    app.run()
    assert counts['materialize_charts']==2
    selected=app.selectbox(key='result_chart_selector')
    selected.set_value(values[1]['chart_id']).run()
    assert counts['materialize_charts']==3
    assert len(app.get('plotly_chart'))==1
    navigate(app,'分析概览')
    assert 1 <= len(app.get('plotly_chart')) <= 2
    assert counts['materialize_charts']==4  # One-entry chart budget; replaced visual cache.


def test_full_table_stable_sort_filter_then_pagination():
    from app.components.result_panel import paginate_result_table
    frame=pd.DataFrame({'value':list(range(251)), 'group':['a']*151+['b']*100})
    page, full, actual=paginate_result_table(frame,page=2,page_size=50,sort_column='value',descending=True)
    assert actual==2 and len(full)==251
    assert page['value'].tolist()==list(range(200,150,-1))
    page,full,_=paginate_result_table(frame,page=2,page_size=50,sort_column='group',filter_column='group',filter_text='a')
    assert len(full)==151 and page['value'].tolist()==list(range(50,100))
    pd.testing.assert_frame_equal(frame,pd.DataFrame({'value':list(range(251)), 'group':['a']*151+['b']*100}))


def test_ui_pagination_changes_only_display(monkeypatch):
    import insightpilot.agents.workflow as workflow
    counts=Counter(); counted(monkeypatch,workflow,'run_agent_analysis',counts)
    app=app_small(); click(app,'开始分析')
    result=app.session_state['last_analysis_result']
    # Test-specific long computed result, not altered raw input; exercise actual page widgets.
    result['result_tables']['pagination_fixture']=pd.DataFrame({'value':range(351),'dimension':['x']*351})
    navigate(app,'结果明细')
    app.selectbox(key='result_table_selector').set_value('pagination_fixture').run()
    assert len(app.dataframe)==1 and len(app.dataframe[-1].value)==100
    page=next(x for x in app.number_input if x.label=='页码')
    page.set_value(2).run()
    assert len(app.dataframe[-1].value)==100
    assert app.dataframe[-1].value.iloc[0,0]==100
    next(x for x in app.selectbox if x.label=='每页行数').set_value(50).run()
    assert len(app.dataframe[-1].value)==50
    assert counts['run_agent_analysis']==1


def test_refresh_and_release_do_not_silently_keep_or_reload_old_data(monkeypatch):
    import app.components.data_source_panel as source
    counts=Counter(); counted(monkeypatch,source,'load_synthetic_tables',counts)
    app=app_small(); click(app,'开始分析')
    revision=app.session_state['performance_dataset'].current.revision
    click(app,'加载 / 刷新当前数据')
    assert counts['load_synthetic_tables']==2
    assert app.session_state['performance_dataset'].current.revision!=revision
    assert any('上次运行结果' in str(x.value) for x in app.warning)
    click(app,'释放本会话数据与结果')
    assert app.session_state['performance_released'] is True
    assert 'performance_dataset' not in session_snapshot(app)
    assert session_snapshot(app).get('last_analysis_result') is None
    app.run()
    assert counts['load_synthetic_tables']==2


def test_pure_sessions_ttl_isolation_and_exact_revision():
    config=replace(PerformanceConfig(),session_ttl_seconds=10)
    clock=[0.0]
    a=DatasetSession(config,clock=lambda:clock[0]); b=DatasetSession(config,clock=lambda:clock[0])
    calls=Counter()
    def loader():
        calls['load']+=1
        return {'x':pd.DataFrame({'metric':[1,2]})},None
    first,hit=a.load('file1',loader,source_type='uploaded_files')
    assert not hit
    second,hit=a.load('file1',loader,source_type='uploaded_files')
    assert hit and first is second and b.current is None
    clock[0]=11
    third,hit=a.load('file1',loader,source_type='uploaded_files')
    assert not hit and first.revision!=third.revision and calls['load']==2


def test_analysis_key_covers_answer_parameters_and_model_versions():
    base={'question':'why','goal':'diagnosis','mapping':{'metric':'orders'},'parameters':{'baseline':7},'filters':{'city':'a'},'plan':{'dimensions':['city']}}
    def key(config=base,catalog='v1',revision='1'):
        return analysis_cache_key(dataset_id='x',dataset_revision=revision,config=config,catalog_version=catalog,computation_version='calc1')
    assert key()!=key(catalog='v2') and key()!=key(revision='2')
    for field,value in [('question','new'),('goal','experiment'),('mapping',{'metric':'revenue'}),('parameters',{'baseline':28}),('filters',{'city':'b'}),('plan',{'dimensions':['channel']})]:
        assert key()!=key({**base,field:value})
    calls=Counter(); session=AnalysisSession(); other=AnalysisSession()
    def compute(): calls['compute']+=1; return {'number':calls['compute']}
    first,hit=session.run(key(),compute); assert not hit
    second,hit=session.run(key(),compute); assert hit and first is second
    assert len(other.cache)==0
    third,hit=session.run(key(),compute,force=True); assert not hit and third!=first and calls['compute']==2


def test_data_budget_rejects_without_truncation():
    config=replace(PerformanceConfig(),dataset_max_bytes=10)
    session=DatasetSession(config)
    with pytest.raises(MemoryBudgetExceeded):
        session.load('oversize',lambda:({'x':pd.DataFrame({'metric':range(100)})},None),source_type='synthetic')
    assert session.current is None


def test_failed_analysis_is_visible_but_explicit_submit_retries():
    clock=[0.0]
    session=AnalysisSession(replace(PerformanceConfig(),session_ttl_seconds=10),clock=lambda:clock[0])
    calls=Counter()
    def failed():
        calls['run']+=1
        return {'execution_status':'FAILED','errors':['temporary failure']}
    first,hit=session.run('same',failed)
    assert not hit and session.current is first and len(session.cache)==0
    second,hit=session.run('same',failed)
    assert not hit and calls['run']==2 and len(session.cache)==0
    clock[0]=11
    assert session.current is None



def test_overview_rerun_expires_hidden_presentation_caches():
    from insightpilot.performance import BoundedCache
    app=app_small()
    dummy={'execution_status':'COMPLETED','summary':'轻量结果','run_manifest':{'run_id':'expiry-fixture'}}
    app.session_state['performance_result'].run('dummy',lambda:dummy)
    app.session_state['last_analysis_result']=dummy
    clock=[0.0]
    caches=[]
    for key in ('performance_chart_cache','performance_table_view_cache','performance_table_csv_cache','performance_export_cache','performance_developer_json_cache'):
        cache=BoundedCache(1,1024,5,clock=lambda:clock[0])
        cache.put('x',b'held')
        app.session_state[key]=cache
        caches.append(cache)
    clock[0]=6
    app.run()
    assert not app.exception and app.session_state['result_tabs']=='分析概览'
    # Do not call len/get/stats here: those would themselves expire and mask missing cleanup.
    assert all(cache._bytes==0 and not cache._items for cache in caches)


def test_upload_raw_bytes_budget_rejects_and_releases_widget(monkeypatch):
    monkeypatch.setenv('INSIGHTPILOT_PERF_DATASET_MAX_BYTES','1024')
    app=app_small('upload')
    raw=b'date,metric\n2026-01-01,1\n'+b'\n'*3000
    app.file_uploader[0].set_value(('large-whitespace.csv',raw,'text/csv')).run()
    assert not app.exception
    assert any('预算' in str(item.value) for item in app.error)
    assert app.file_uploader[0].value in (None,[])
    assert app.session_state['performance_dataset'].current is None
    assert app.session_state['uploaded_widget_epoch']==1
    assert 'performance_upload_files' not in session_snapshot(app)


def test_parsed_tables_and_retained_source_share_dataset_budget():
    session=DatasetSession(replace(PerformanceConfig(),dataset_max_bytes=2048))
    with pytest.raises(MemoryBudgetExceeded):
        session.load('file',lambda:({'x':pd.DataFrame({'metric':range(100)})},None),source_type='uploaded_files',retained_source_bytes=1600)
    assert session.current is None


def test_catalog_digest_detects_same_length_same_mtime_change(tmp_path):
    import os
    from app.session_data import catalog_version
    directory=tmp_path/'insightpilot/semantic/models'
    directory.mkdir(parents=True)
    path=directory/'model.yaml'
    path.write_bytes(b'metric: first\n')
    before=path.stat()
    first=catalog_version(tmp_path)
    path.write_bytes(b'metric: other\n')
    os.utime(path,ns=(before.st_atime_ns,before.st_mtime_ns))
    assert path.stat().st_size==before.st_size and path.stat().st_mtime_ns==before.st_mtime_ns
    assert catalog_version(tmp_path)!=first


def test_chart_budget_failure_is_visible_without_crashing(monkeypatch):
    monkeypatch.setenv('INSIGHTPILOT_PERF_RESULT_MAX_BYTES','1024')
    app=AppTest.from_string("""
import streamlit as st
import pandas as pd
from app.components.result_panel import _render_visuals
_render_visuals({'run_manifest': {'run_id':'small'}, 'chart_specs':[{'chart_id':'c','chart_type':'line','title':'小图','table_key':'x','x':'x','y':['y']}], 'result_tables':{'x':pd.DataFrame({'x':[1,2],'y':[3,4]})}})
""").run()
    assert not app.exception
    assert any('预算' in str(x.value) for x in app.warning)
    assert len(app.get('plotly_chart'))==0
