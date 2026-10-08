"""Measure real in-memory CSV/Excel reads against an explicit source checkout."""
from __future__ import annotations
import argparse,io,json,statistics,sys,time
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--source-root',type=Path);p.add_argument('--output',type=Path,required=True);args=p.parse_args()
if args.source_root:sys.path.insert(0,str(args.source_root.resolve()))
import numpy as np
import pandas as pd
from insightpilot.ingestion.file_loader import read_csv_file,read_excel_file,get_excel_sheet_names
from insightpilot.ingestion.table_registry import TableRegistry
from insightpilot.reports.manifest import fingerprint_dataframe
import insightpilot
rng=np.random.default_rng(42);n=100000
frame=pd.DataFrame({'日期':pd.Timestamp('2026-01-01')+pd.to_timedelta(np.arange(n)%180,unit='D'),'用户编号':np.arange(n),'城市':np.array(['北京','上海','深圳','成都'])[np.arange(n)%4],'渠道':np.array(['搜索','推荐','活动'])[np.arange(n)%3],'收入':rng.integers(1,10000,n)/100,'订单':rng.integers(1,10,n),'会话':rng.integers(10,100,n),'实验组':np.array(['control','treatment'])[np.arange(n)%2],'完播率':rng.uniform(.1,.9,n),'设备':np.array(['Android','iOS'])[np.arange(n)%2]})
csv=frame.to_csv(index=False).encode('utf-8-sig');buffer=io.BytesIO()
with pd.ExcelWriter(buffer,engine='openpyxl') as writer:
    frame.iloc[:20000].to_excel(writer,sheet_name='分析表',index=False)
    frame.iloc[:50].to_excel(writer,sheet_name='小型参考表',index=False)
xlsx=buffer.getvalue();records=[]
for kind,data,rows in [('csv',csv,100000),('excel',xlsx,20000)]:
    for repeat in range(1,4):
        stream=io.BytesIO(data);stream.name='synthetic.'+('csv' if kind=='csv' else 'xlsx');times={}
        if kind=='excel':
            t=time.perf_counter();sheets=get_excel_sheet_names(stream);times['sheet_names']=time.perf_counter()-t;assert sheets==['分析表','小型参考表']
        t=time.perf_counter();loaded=read_csv_file(stream,encoding='utf-8-sig') if kind=='csv' else read_excel_file(stream,sheet_name='分析表');times['parse']=time.perf_counter()-t
        assert len(loaded.dataframe)==rows and loaded.dataframe.shape[1]==10
        t=time.perf_counter();registry=TableRegistry();registry.add_table(loaded.name,loaded.dataframe,'uploaded_file',stream.name);times['registry_quality_schema']=time.perf_counter()-t
        t=time.perf_counter();digest=fingerprint_dataframe(loaded.dataframe);times['exact_fingerprint']=time.perf_counter()-t
        records.append({'format':kind,'repeat':repeat,'rows':rows,'columns':10,'input_bytes':len(data),'times':times,'fingerprint':digest,'dataframe_deep_bytes':int(loaded.dataframe.memory_usage(deep=True).sum())})
summary={kind:{phase:{'median':statistics.median(x['times'][phase] for x in records if x['format']==kind),'min':min(x['times'][phase] for x in records if x['format']==kind),'max':max(x['times'][phase] for x in records if x['format']==kind)} for phase in records[0 if kind=='csv' else 3]['times']} for kind in ['csv','excel']}
args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps({'source_file':insightpilot.__file__,'method':'perf_counter, same-process three reads; fixtures synthetic and only in BytesIO; CSV100k and selected Excel20k; generation excluded; deep bytes not RSS','records':records,'summary':summary},ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps(summary,ensure_ascii=False))
