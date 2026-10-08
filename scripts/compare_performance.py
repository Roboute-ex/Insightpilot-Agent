"""Compare measured timings and every saved numeric/result value, without updating expectations."""
from __future__ import annotations
import argparse,json,math
from pathlib import Path


def differences(before,after,path='$',column=None):
    errors=[]
    if isinstance(before,bool) or isinstance(after,bool):
        if before!=after or type(before)!=type(after):errors.append({'path':path,'before':before,'after':after})
    elif isinstance(before,(int,float)) and isinstance(after,(int,float)):
        exact=isinstance(before,int) and isinstance(after,int) or column is not None and any(k in column for k in ['sample_size','row_count','duplicate_rows'])
        abs_tol=1e-300 if 'p_value' in path or column=='p_value' else 1e-12
        equal=before==after if exact else math.isclose(before,after,rel_tol=1e-10,abs_tol=abs_tol)
        if not equal:errors.append({'path':path,'before':before,'after':after})
    elif isinstance(before,dict) and isinstance(after,dict):
        if set(before)!=set(after):errors.append({'path':path,'before_keys':list(before),'after_keys':list(after)})
        for key in before.keys()&after.keys():errors.extend(differences(before[key],after[key],path+'.'+str(key),str(key)))
    elif isinstance(before,list) and isinstance(after,list):
        if len(before)!=len(after):errors.append({'path':path,'before_length':len(before),'after_length':len(after)})
        for i,(a,b) in enumerate(zip(before,after)):errors.extend(differences(a,b,f'{path}[{i}]',column))
    elif before!=after:errors.append({'path':path,'before':before,'after':after})
    return errors


def compare_tables(a,b):
    errors=[]
    if set(a)!=set(b):errors.append({'path':'tables','before':list(a),'after':list(b)})
    for table in a.keys()&b.keys():
        av,bv=a[table],b[table]
        errors.extend(differences(av['columns'],bv['columns'],table+'.columns'))
        if len(av['rows'])!=len(bv['rows']):errors.append({'path':table+'.rows','before':len(av['rows']),'after':len(bv['rows'])})
        for index,(ar,br) in enumerate(zip(av['rows'],bv['rows'])):
            for column,x,y in zip(av['columns'],ar,br):errors.extend(differences(x,y,f'{table}[{index}].{column}',column))
    return errors


def main():
    p=argparse.ArgumentParser();p.add_argument('--before',type=Path,required=True);p.add_argument('--after',type=Path,required=True);p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    records=[];failures=[]
    files=sorted(args.before.glob('*.reference.json'))
    if not files:raise SystemExit('No before reference data')
    for old in files:
        new=args.after/old.name
        if not new.exists():failures.append({'file':old.name,'error':'after reference missing'});continue
        before=json.loads(old.read_text(encoding='utf-8'));after=json.loads(new.read_text(encoding='utf-8'));errors=compare_tables(before,after)
        records.append({'file':old.name,'table_count':len(before),'rows':sum(len(x['rows']) for x in before.values()),'passed':not errors,'differences':errors[:30]})
        if errors:failures.extend({'file':old.name,**e} for e in errors)
    bs=json.loads((args.before/'summary.json').read_text(encoding='utf-8'));ats=json.loads((args.after/'summary.json').read_text(encoding='utf-8'));times=[]
    for b in bs:
        a=next((x for x in ats if (x['case'],x['rows'])==(b['case'],b['rows'])),None)
        if a is None:continue
        stages={k:{'before_seconds':v['median'],'after_seconds':a['stages'][k]['median'],'ratio_after_over_before':a['stages'][k]['median']/v['median'] if v['median'] else None} for k,v in b['stages'].items() if k in a['stages']}
        times.append({'case':b['case'],'rows':b['rows'],'stages':stages,'before_peak_rss_bytes':b['rss_peak_bytes']['max'],'after_peak_rss_bytes':a['rss_peak_bytes']['max']})
    output={'passed':not failures,'method':'All saved tables, columns, ordered rows and nested evidence checked. Counts exact; float rtol=1e-10/atol=1e-12; p-values use atol=1e-300. No expected values updated.','before':str(args.before.resolve()),'after':str(args.after.resolve()),'reference_checks':records,'difference_count':len(failures),'differences':failures[:100],'timings':times}
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps({'passed':not failures,'files':len(records),'tables':sum(x['table_count'] for x in records),'differences':len(failures)},ensure_ascii=False));return int(bool(failures))
if __name__=='__main__':raise SystemExit(main())
