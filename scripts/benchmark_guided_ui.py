"""Fresh-process AppTest benchmarks with synthetic data, call counters and native RSS."""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import functools,json,os,statistics,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def child(args):
    source=args.source_root.resolve();sys.path.insert(0,str(source));os.environ['INSIGHTPILOT_UI_SYNC']='1'
    from benchmark_performance import MemorySample
    from streamlit.testing.v1 import AppTest
    import insightpilot.agents.workflow as workflow
    import insightpilot.agents.dataset as dataset
    import insightpilot.planning.planner as planner
    import app.components.data_source_panel as data
    import app.components.export_panel as exports
    import app.background_tasks as tasks
    from insightpilot.tools.duckdb_engine import AnalyticsEngine
    assert Path(workflow.__file__).resolve().is_relative_to(source)
    counts=Counter();timings=defaultdict(float);phase_counts={};stages={}
    targets=[(data,'load_synthetic_tables'),(dataset,'infer_schema_mapping'),(dataset,'fingerprint_dataframe'),(workflow,'run_agent_analysis'),(workflow,'_run_routed_analysis'),(workflow,'_run_playbook_node'),(planner,'prepare_analysis_request'),(exports,'prepare_export_payload'),(tasks,'request_work'),(AnalyticsEngine,'run_parameterized_sql')]
    for module,name in targets:
        original=getattr(module,name)
        @functools.wraps(original)
        def wrapped(*a,_fn=original,_name=name,**kw):
            counts[_name]+=1;start=time.perf_counter()
            try:return _fn(*a,**kw)
            finally:timings[_name]+=time.perf_counter()-start
        setattr(module,name,wrapped)
    with MemorySample() as memory:
        def measure(name,fn):
            before=counts.copy();memory.phase=name;start=time.perf_counter();value=fn()
            stages[name]=time.perf_counter()-start;phase_counts[name]=dict(counts-before)
            assert not app.exception,[x.message for x in app.exception]
            return value
        app=AppTest.from_file(str(source/'app/ui_streamlit.py'),default_timeout=120)
        app.session_state['demo_scale']='standard';app.session_state['data_source_selector']='synthetic'
        measure('initial_data_ready',app.run)
        def click(label):next(x for x in app.button if x.label==label).click().run()
        def nav(label):app.session_state['requested_result_tab']=label;app.run()
        initial={'playbook':app.session_state['playbook_selector'],'visible_text_inputs':[x.label for x in app.text_input],'visible_selectboxes':[x.label for x in app.selectbox],'mode_controls':len(app.segmented_control)}
        measure('question_advice',lambda:app.text_input(key='question').set_value('昨日订单量为什么下降？').run())
        measure('analysis_first',lambda:click('开始分析'))
        result=app.session_state['last_analysis_result'];assert result['execution_status']=='COMPLETED',result.get('errors')
        first_run=result['run_manifest']['run_id']
        measure('analysis_repeat',lambda:click('开始分析'));assert app.session_state['last_analysis_result']['run_manifest']['run_id']==first_run
        measure('details_page',lambda:nav('结果明细'));measure('overview_page',lambda:nav('分析概览'));measure('report_page',lambda:nav('报告导出'))
        export_calls_before=counts['prepare_export_payload']
        for name,label in [('pdf','生成 PDF 报告'),('excel','生成 Excel 报告'),('zip_warm','生成 ZIP 报告包')]:measure('export_'+name,lambda label=label:click(label))
        snapshot=app.session_state['performance_dataset'].current;cache=app.session_state['performance_result']
        record={'source':str(source),'initial':initial,'scale':'standard','seed':42,'stages':stages,'phase_calls':phase_counts,'total_calls':dict(counts),'function_seconds':dict(timings),'unrequested_exports':export_calls_before,'tables':{name:{'rows':len(df),'columns':len(df.columns)} for name,df in snapshot.tables.items()},'fingerprints':snapshot.fingerprints,'retained_dataset_bytes':snapshot.estimated_bytes,'cache_budgets':{'dataset':app.session_state['performance_dataset'].cache.max_bytes,'result':cache.config.result_max_bytes,'history':cache.history_reserved_bytes},'execution_status':result['execution_status'],'exceptions':[x.message for x in app.exception],'result_rows':{k:len(v) for k,v in result['result_tables'].items()}}
        assert export_calls_before==0
        assert phase_counts['question_advice'].get('run_agent_analysis',0)==0
        for name in ('analysis_repeat','details_page','overview_page','report_page'):
            assert phase_counts[name].get('run_agent_analysis',0)==0
            assert phase_counts[name].get('fingerprint_dataframe',0)==0
    record['memory']=memory.summary();args.output.write_text(json.dumps(record,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8')
    print(json.dumps({'first':stages['analysis_first'],'repeat':stages['analysis_repeat'],'rss':record['memory']['sampled_peak_bytes']}));return 0

def main():
    p=argparse.ArgumentParser();p.add_argument('--source-root',type=Path,default=ROOT);p.add_argument('--output-dir',type=Path,required=True);p.add_argument('--repeat',type=int,default=3);p.add_argument('--child',action='store_true');p.add_argument('--output',type=Path);args=p.parse_args()
    if args.child:return child(args)
    args.output_dir.mkdir(parents=True,exist_ok=False);runs=[]
    for index in range(args.repeat):
        target=args.output_dir/f'run-{index+1}.json';command=[sys.executable,str(Path(__file__).resolve()),'--source-root',str(args.source_root.resolve()),'--output-dir',str(args.output_dir.resolve()),'--child','--output',str(target.resolve())]
        env=dict(os.environ,PYTHONUTF8='1',PYTHONDONTWRITEBYTECODE='1');env.pop('PYTHONPATH',None)
        proc=subprocess.run(command,cwd=args.source_root,env=env,capture_output=True,text=True,encoding='utf-8',timeout=600)
        target.with_suffix('.stdout.txt').write_text(proc.stdout,encoding='utf-8');target.with_suffix('.stderr.txt').write_text(proc.stderr,encoding='utf-8')
        print(json.dumps({'iteration':index+1,'exit_code':proc.returncode,'record':str(target)}),flush=True)
        if proc.returncode:return proc.returncode
        runs.append(json.loads(target.read_text(encoding='utf-8')))
    def summary(values):return {'median':statistics.median(values),'min':min(values),'max':max(values)}
    result={'method':'Fresh Python/AppTest per repetition; standard seed42; synchronous UI isolates rendering. ZIP reuses PDF/Excel. Native RSS sampled every20ms.','source':str(args.source_root.resolve()),'repeats':len(runs),'stages':{k:summary([r['stages'][k] for r in runs]) for k in runs[0]['stages']},'rss_peak_bytes':summary([r['memory']['sampled_peak_bytes'] for r in runs]),'counts':runs[0]['phase_calls'],'tables':runs[0]['tables'],'cache_budgets':runs[0]['cache_budgets']}
    (args.output_dir/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');return 0
if __name__=='__main__':raise SystemExit(main())
