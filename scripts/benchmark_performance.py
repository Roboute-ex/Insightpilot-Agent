"""Synthetic-only performance benchmark; records full results, native RSS and actual calls."""
from __future__ import annotations
import argparse
from collections import defaultdict
from contextlib import contextmanager
import datetime as dt
import functools
import gc
import importlib.metadata as md
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import threading
import time
ROOT=Path(__file__).resolve().parents[1]

def rss_bytes():
    if os.name=='nt':
        import ctypes
        from ctypes import wintypes
        class Counters(ctypes.Structure):
            _fields_=[('cb',wintypes.DWORD),('PageFaultCount',wintypes.DWORD),('PeakWorkingSetSize',ctypes.c_size_t),('WorkingSetSize',ctypes.c_size_t),('QuotaPeakPagedPoolUsage',ctypes.c_size_t),('QuotaPagedPoolUsage',ctypes.c_size_t),('QuotaPeakNonPagedPoolUsage',ctypes.c_size_t),('QuotaNonPagedPoolUsage',ctypes.c_size_t),('PagefileUsage',ctypes.c_size_t),('PeakPagefileUsage',ctypes.c_size_t)]
        c=Counters();c.cb=ctypes.sizeof(c)
        ctypes.windll.kernel32.GetCurrentProcess.restype=wintypes.HANDLE
        ctypes.windll.psapi.GetProcessMemoryInfo.argtypes=[wintypes.HANDLE,ctypes.c_void_p,wintypes.DWORD]
        if ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.windll.kernel32.GetCurrentProcess(),ctypes.byref(c),c.cb):return int(c.WorkingSetSize),int(c.PeakWorkingSetSize)
    try:
        import psutil
        r=psutil.Process().memory_info();return r.rss,getattr(r,'peak_wset',r.rss)
    except ImportError:
        p=Path('/proc/self/statm')
        if p.exists():return int(p.read_text().split()[1])*os.sysconf('SC_PAGE_SIZE'),None
    return None,None

class MemorySample:
    def __init__(self):self.samples=[];self.phase='startup';self.stop=threading.Event()
    def __enter__(self):
        initial_rss,initial_peak=rss_bytes()
        if initial_rss is None:raise RuntimeError("RSS measurement unavailable; install optional psutil")
        self.samples.append((time.perf_counter(),self.phase,initial_rss,initial_peak))
        def collect():
            while not self.stop.is_set():
                rss,peak=rss_bytes();self.samples.append((time.perf_counter(),self.phase,rss,peak));self.stop.wait(.02)
        self.thread=threading.Thread(target=collect,daemon=True);self.thread.start();return self
    def __exit__(self,*args):self.stop.set();self.thread.join()
    def summary(self):
        phases=defaultdict(list)
        for _,phase,rss,_ in self.samples:
            if rss is not None:phases[phase].append(rss)
        return {'method':'20ms sampled process RSS / Windows OS lifetime PeakWorkingSetSize; native memory included; no tracemalloc','sampling_interval_ms':20,'samples':len(self.samples),'sampled_peak_bytes':max((s[2] or 0 for s in self.samples),default=0),'os_lifetime_peak_bytes':max((s[3] or 0 for s in self.samples),default=0),'phase_sampled_peak_bytes':{k:max(v) for k,v in phases.items()}}

def make_data(case,rows,seed,scale="standard"):
    import numpy as np
    import pandas as pd
    if case!='rows':
        from insightpilot.data.scenarios import generate_scenario
        q,goal={'transaction':('昨日订单量为什么下降？','metric_diagnosis'),'content':('新策略是否提升了内容完播率？','experiment_analysis'),'live':('请定位直播体验异常的主要维度。','live_quality')}[case]
        return generate_scenario(case,scale=scale,seed=seed).tables,{'question':q,'goal_mode':goal}
    rng=np.random.default_rng(seed);n=rows;day=rng.integers(0,180,n)
    sessions=rng.integers(10,100,n);orders=rng.binomial(sessions,.21)
    df=pd.DataFrame({'date':pd.Timestamp('2026-01-01')+pd.to_timedelta(day,unit='D'),'event_id':np.arange(n,dtype=np.int64),'user_id':rng.integers(0,max(1000,n//5),n),'city':np.array([f'城市{x:02}' for x in range(16)])[rng.integers(0,16,n)],'channel':np.array(['搜索','推荐','广告','直接','活动','社交'])[rng.integers(0,6,n)],'device':np.array(['Android','iOS','Web'])[rng.integers(0,3,n)],'sessions':sessions,'orders':orders,'revenue':np.round(orders*rng.uniform(30,80,n),2),'conversion_rate':orders/sessions})
    return {'benchmark':df},{'question':'请分析订单和收入的趋势与城市结构。','goal_mode':'metric_diagnosis','data_source_type':'uploaded_files','column_mapping':{'table_name':'benchmark','date_column':'date','metric_columns':['orders','revenue'],'dimension_columns':['city','channel'],'aggregation':'sum','time_grain':'day'}}

def _json_default(value):
    if hasattr(value,'item'):return value.item()
    if hasattr(value,'isoformat'):return value.isoformat()
    return str(value)

def child(args):
    sys.path.insert(0, str((args.source_root or ROOT).resolve()))
    start=time.perf_counter();record={'case':args.case,'requested_rows':args.rows,'seed':args.seed,'repeat':args.iteration,'label':args.label,'python':sys.version,'pid':os.getpid(),'stages':{},'session_path':args.session_path,'scale':args.scale}
    phase='imports';calls=defaultdict(lambda:defaultdict(lambda:{'count':0,'seconds':0.0}));spans=defaultdict(list)
    with MemorySample() as memory:
        import pandas as pd
        import insightpilot.agents.workflow as workflow
        record['source_file']=workflow.__file__
        if args.source_root and not Path(workflow.__file__).resolve().is_relative_to(args.source_root.resolve()):raise RuntimeError('Requested source root was not imported')
        from insightpilot.observability import LocalTracer
        import insightpilot.ingestion.schema_mapper as schema
        import insightpilot.ingestion.validation as validation
        import insightpilot.reports.manifest as manifests
        import insightpilot.reports.pdf as pdf
        import insightpilot.reports.html as html
        import insightpilot.reports.excel as excel
        import insightpilot.reports.markdown as markdown
        from insightpilot.reports.bundle import generate_export_bundle
        import insightpilot.visualization.factory as factory
        from insightpilot.tools.duckdb_engine import AnalyticsEngine
        record['stages']['imports']=time.perf_counter()-start
        targets={}
        for mod,name,label in [(schema,'infer_schema_mapping','schema_profile'),(validation,'validate_dataframe_for_analysis','quality'),(manifests,'fingerprint_dataframe','exact_fingerprint'),(workflow,'_safe_engine','table_registration'),(workflow,'_build_analysis_results_node','result_package'),(workflow,'_build_result_from_state','result_protocol'),(workflow,'_review_node','reviewer'),(workflow,'_run_routed_analysis','statistics'),(workflow,'_run_playbook_node','statistics_playbook'),(factory,'build_charts','chart_build'),(markdown,'generate_markdown_report','export_markdown'),(pdf,'generate_pdf_report','export_pdf'),(html,'generate_html_report','export_html'),(excel,'generate_excel_report','export_excel')]:
            f=getattr(mod,name,None)
            if callable(f):targets[f]=label
        targets[AnalyticsEngine.run_parameterized_sql]="actual_sql_execute"
        wrapped={}
        for original,label in targets.items():
            def make(original,label):
                @functools.wraps(original)
                def wrapper(*a,**kw):
                    t=time.perf_counter()
                    try:return original(*a,**kw)
                    finally:
                        c=calls[phase][label];c['count']+=1;c['seconds']+=time.perf_counter()-t
                return wrapper
            wrapped[original]=make(original,label)
        for module in list(sys.modules.values()):
            if module is None or not getattr(module,'__name__','').startswith(('insightpilot.','app.')):continue
            for name,value in list(vars(module).items()):
                try:w=wrapped.get(value)
                except TypeError:continue
                if w is not None:setattr(module,name,w)
        AnalyticsEngine.run_parameterized_sql=wrapped[AnalyticsEngine.run_parameterized_sql]
        end_span=LocalTracer.end_span
        def measured_end(self,span,*a,**kw):
            out=end_span(self,span,*a,**kw);spans[phase].append(out.to_dict());return out
        LocalTracer.end_span=measured_end
        @contextmanager
        def measure(name):
            nonlocal phase
            phase=name;memory.phase=name;t=time.perf_counter()
            try:yield
            finally:record['stages'][name]=time.perf_counter()-t
        with measure('data_loading'):tables,config=make_data(args.case,args.rows,args.seed,args.scale)
        if args.session_path:
            from app.session_data import DatasetSession,AnalysisSession,analysis_cache_key
            from app.session_data import catalog_version
            from insightpilot.performance import PerformanceConfig
            policy=PerformanceConfig.from_environment();data_session=DatasetSession(policy);analysis_session=AnalysisSession(policy)
            with measure('dataset_preparation'):
                snapshot,_=data_session.load((args.case,args.rows,args.seed,args.scale),lambda:(tables,None),source_type=config.get('data_source_type','synthetic'))
                tables=snapshot.tables
            key=analysis_cache_key(dataset_id=snapshot.dataset_id,dataset_revision=snapshot.revision,config=config,catalog_version=catalog_version(ROOT),computation_version=policy.computation_version)
            compute=lambda:workflow.run_agent_analysis(tables={},prepared_dataset=snapshot.prepared,presentation_mode='deferred',**config)
            with measure('analysis_first'):result,first_hit=analysis_session.run(key,compute)
            with measure('analysis_repeat'):repeated,repeat_hit=analysis_session.run(key,compute)
            assert not first_hit and repeat_hit
            record['analysis_cache_hits']={'first':first_hit,'repeat':repeat_hit}
            record['session_cache_stats']={'dataset':data_session.cache.stats(),'analysis':analysis_session.cache.stats()}
        else:
            with measure('analysis_first'):result=workflow.run_agent_analysis(tables=tables,**config)
            with measure('analysis_repeat'):repeated=workflow.run_agent_analysis(tables=tables,**config)
        assert result.get('execution_status')=='COMPLETED',result.get('errors')
        assert repeated.get('execution_status')=='COMPLETED',repeated.get('errors')
        del repeated;gc.collect()
        if args.profile:
            import cProfile,pstats
            pr=cProfile.Profile();pr.enable();workflow.run_agent_analysis(tables=tables,**config);pr.disable();pr.dump_stats(str(args.output.with_suffix('.prof')))
            with args.output.with_suffix('.profile.txt').open('w',encoding='utf-8') as f:pstats.Stats(pr,stream=f).sort_stats('cumulative').print_stats(70)
        figures=result.get('charts',[])
        if args.session_path:
            from insightpilot.visualization.result_charts import materialize_charts
            with measure('chart_materialize_requested'):figures=[figure for _,figure in materialize_charts(result)]
        with measure('chart_serialization'):chart_json=[figure.to_json() for figure in figures]
        record['chart_json_bytes']=sum(len(x.encode('utf-8')) for x in chart_json)
        record['chart_points']=sum(len(trace.x) if getattr(trace,'x',None) is not None else len(trace.y) if getattr(trace,'y',None) is not None else 0 for figure in figures for trace in figure.data)
        del chart_json
        manifest=manifests.RunManifest.from_dict(result['run_manifest']);payloads={}
        for format_name,fn in [('pdf',lambda:pdf.generate_pdf_report(result,manifest)),('markdown',lambda:markdown.generate_markdown_report(result)),('html',lambda:html.generate_html_report(result,result.get('charts',[]),manifest)),('excel',lambda:excel.generate_excel_report(result,manifest)),('manifest',manifest.to_json)]:
            with measure('export_'+format_name):payloads[format_name]=fn()
        with measure('export_zip_assembly'):payloads['bundle']=generate_export_bundle(payloads['markdown'],payloads['html'],payloads['excel'],payloads['manifest'],result.get('result_tables',{}),pdf_bytes=payloads['pdf'])
        record['export_bytes']={k:len(v.encode('utf-8') if isinstance(v,str) else v) for k,v in payloads.items()}
        record['stages']['export_zip_cold_total']=sum(record['stages']['export_'+k] for k in ('pdf','markdown','html','excel','manifest','zip_assembly'))
        del payloads
        with measure('measurement_data_description'):
            record['tables']={name:{'rows':len(df),'columns':len(df.columns),'memory_deep_bytes':int(df.memory_usage(deep=True).sum()),'string_column_fraction':sum(pd.api.types.is_string_dtype(df[c]) and not pd.api.types.is_numeric_dtype(df[c]) for c in df.columns)/max(1,len(df.columns)),'dimension_cardinalities':{str(c):int(df[c].nunique(dropna=False)) for c in df.select_dtypes(include=['object','string','category']).columns}} for name,df in tables.items()}
        reference={}
        for name,df in result.get('result_tables',{}).items():
            if not isinstance(df,pd.DataFrame):continue
            if len(df)>20000:raise ValueError('Benchmark result exceeds aggregate reference limit')
            reference[name]={'columns':list(map(str,df.columns)),'rows':json.loads(df.to_json(orient='values',date_format='iso',double_precision=15))}
        args.output.with_suffix('.reference.json').write_text(json.dumps(reference,ensure_ascii=False,default=_json_default)+'\n',encoding='utf-8')
        record['result_table_rows']={k:len(v) for k,v in result.get('result_tables',{}).items() if isinstance(v,pd.DataFrame)}
        record['execution_status']=result['execution_status'];record['trace_operation_records']=len(result.get('trace',{}).get('executed_queries',[]));record['actual_sql_execute_calls']=calls['analysis_first'].get('actual_sql_execute',{}).get('count',0);record['function_calls']=dict(calls);record['workflow_spans']=dict(spans)
        record['packages']={n:md.version(n) for n in ['insightpilot-agent','pandas','numpy','duckdb','streamlit','plotly','reportlab','scipy','openpyxl']}
        record['elapsed_child_seconds']=time.perf_counter()-start
    record['memory']=memory.summary()
    args.output.write_text(json.dumps(record,ensure_ascii=False,indent=2,default=_json_default)+'\n',encoding='utf-8')
    print(json.dumps({'case':args.case,'rows':args.rows,'first':record['stages']['analysis_first'],'repeat':record['stages']['analysis_repeat'],'rss_peak_mb':record['memory']['sampled_peak_bytes']/1024**2},ensure_ascii=False),flush=True);return 0

def main():
    p=argparse.ArgumentParser();p.add_argument('--output-dir',type=Path,default=ROOT/'reports/performance');p.add_argument('--label',default='measurement');p.add_argument('--repeat',type=int,default=3);p.add_argument('--case',choices=['all','transaction','content','live','rows'],default='all');p.add_argument('--rows',type=int,default=100000);p.add_argument('--seed',type=int,default=42);p.add_argument('--child',action='store_true');p.add_argument('--iteration',type=int,default=1);p.add_argument('--output',type=Path);p.add_argument('--profile',action='store_true');p.add_argument('--session-path',action='store_true');p.add_argument('--source-root',type=Path);p.add_argument('--scale',choices=['small','standard','large'],default='standard');args=p.parse_args()
    if args.child:return child(args)
    folder=args.output_dir/(args.label+'-'+dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'));folder.mkdir(parents=True,exist_ok=False)
    cases=[('transaction',0),('content',0),('live',0),('rows',100000),('rows',500000),('rows',1000000)] if args.case=='all' else [(args.case,args.rows)]
    records=[];env=dict(os.environ,PYTHONUTF8='1',PYTHONDONTWRITEBYTECODE='1');env.pop('PYTHONPATH',None)
    for case,rows in cases:
        for repeat in range(1,args.repeat+1):
            output=folder/f'{case}-{rows}-{repeat}.json';command=[sys.executable,str(Path(__file__).resolve()),'--child','--case',case,'--rows',str(rows),'--iteration',str(repeat),'--seed',str(args.seed),'--label',args.label,'--output',str(output),'--scale',args.scale]
            if args.profile and repeat==1:command+=['--profile']
            if args.session_path:command+=['--session-path']
            if args.source_root:command+=['--source-root',str(args.source_root.resolve())]
            t=time.perf_counter();r=subprocess.run(command,cwd=ROOT,env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=1200)
            output.with_suffix('.stdout.txt').write_text(r.stdout,encoding='utf-8');output.with_suffix('.stderr.txt').write_text(r.stderr,encoding='utf-8')
            record={'case':case,'rows':rows,'repeat':repeat,'exit_code':r.returncode,'process_wall_seconds':time.perf_counter()-t,'record':str(output)};records.append(record)
            (folder/'runs.json').write_text(json.dumps(records,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps(record),flush=True)
            if r.returncode:return r.returncode
    summary=[]
    for case,rows in cases:
        items=[json.loads(Path(r['record']).read_text(encoding='utf-8')) for r in records if r['case']==case and r['rows']==rows]
        stages={k:{'median':statistics.median(x['stages'][k] for x in items),'min':min(x['stages'][k] for x in items),'max':max(x['stages'][k] for x in items)} for k in items[0]['stages']}
        summary.append({'case':case,'rows':rows,'repetitions':len(items),'stages':stages,'rss_peak_bytes':{'median':statistics.median(x['memory']['sampled_peak_bytes'] for x in items),'max':max(x['memory']['sampled_peak_bytes'] for x in items)},'tables':items[0]['tables']})
    (folder/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(str(folder),flush=True);return 0
if __name__=='__main__':raise SystemExit(main())
