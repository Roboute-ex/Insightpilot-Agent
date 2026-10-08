"""Real Chrome measurements, isolated browser context; UI completion plus two animation frames."""
import argparse,json,time,statistics
from pathlib import Path
from playwright.sync_api import sync_playwright
from streamlit.proto.ForwardMsg_pb2 import ForwardMsg
p=argparse.ArgumentParser();p.add_argument('--url',default='http://127.0.0.1:8503');p.add_argument('--output',type=Path,required=True);p.add_argument('--scale',choices=['standard','large'],default='standard');p.add_argument('--ui-version',choices=['before','p0','p1'],default='p1');args=p.parse_args()
args.output.parent.mkdir(parents=True,exist_ok=True)
records=[]
with sync_playwright() as pw:
    browser=pw.chromium.launch(executable_path=r'C:\Program Files\Google\Chrome\Application\chrome.exe',headless=True,chromium_sandbox=True)
    for repeat in range(1,4):
        context=browser.new_context(viewport={'width':1500,'height':1060},accept_downloads=True)
        page=context.new_page(); traffic=[0];finished=[0];errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        def frame_received(frame):
            traffic[0]+=len(frame.encode('utf-8') if isinstance(frame,str) else frame)
            if isinstance(frame,bytes):
                msg=ForwardMsg()
                try:msg.ParseFromString(frame)
                except Exception:return
                if msg.WhichOneof('type')=='script_finished' and msg.script_finished in (0,3):finished[0]+=1
        page.on('websocket',lambda ws:ws.on('framereceived',frame_received))
        page.add_init_script("window.__longTasks=[];new PerformanceObserver(l=>l.getEntries().forEach(x=>window.__longTasks.push(x.duration))).observe({type:'longtask',buffered:true});")
        def idle():
            page.locator('[data-testid="stStatusWidget"]').wait_for(state='hidden',timeout=180000)
            page.evaluate('()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')
        def operation(name,action,after=None):
            previous=traffic[0];previous_finished=finished[0];t=time.perf_counter();action()
            deadline=time.perf_counter()+180
            while finished[0]<=previous_finished:
                if time.perf_counter()>deadline:raise TimeoutError('Streamlit script_finished event not received')
                page.wait_for_timeout(20)
            idle()
            submit_response_seconds=time.perf_counter()-t
            if after:
                try:after()
                except Exception:
                    page.screenshot(path=str(args.output.parent/f'failure-{repeat}-{name}.png'),full_page=True)
                    (args.output.parent/f'failure-{repeat}-{name}.txt').write_text(page.locator('body').inner_text(),encoding='utf-8')
                    raise
            idle();seconds=time.perf_counter()-t
            row={'repeat':repeat,'name':name,'seconds':seconds,'submit_response_seconds':submit_response_seconds,'received_websocket_bytes':traffic[0]-previous,'plotly_elements':page.locator('.js-plotly-plot').count(),'dataframes':page.locator('[data-testid="stDataFrame"]').count()};records.append(row);print(json.dumps(row),flush=True)
            args.output.write_text(json.dumps({'method':'fresh browser context; same warm server; click to actual ForwardMsg.script_finished, idle and two animation frames; 20ms event polling','scale':args.scale,'ui_version':args.ui_version,'chrome_version':browser.version,'records':records},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        t=time.perf_counter();page.goto(args.url,wait_until='domcontentloaded');page.get_by_role('button',name='开始分析').wait_for(timeout=180000);idle();records.append({'repeat':repeat,'name':'initial_navigation','seconds':time.perf_counter()-t,'received_websocket_bytes':traffic[0]})
        if args.scale=='large':
            operation('select_large_source',lambda:(page.get_by_role('combobox',name='数据规模',exact=True).click(),page.get_by_role('option',name='大型',exact=True).click()),lambda:page.get_by_role('button',name='开始分析').wait_for(timeout=180000))
        operation('analysis_first',lambda:page.get_by_role('button',name='开始分析').click(),lambda:page.get_by_role('tab',name='报告导出').wait_for(timeout=180000))
        operation('analysis_repeat',lambda:page.get_by_role('button',name='开始分析').click())
        operation('results_tab',lambda:page.get_by_role('tab',name='结果明细').click())
        operation('visual_tab',lambda:page.get_by_role('tab',name='可视化诊断').click(),lambda:page.locator('.js-plotly-plot').first.wait_for(state='visible',timeout=30000))
        operation('overview_tab',lambda:page.get_by_role('tab',name='分析概览').click())
        operation('professional_mode',lambda:page.get_by_text('专业分析',exact=True).click())
        operation('demo_mode',lambda:page.get_by_text('简洁演示',exact=True).click())
        operation('export_tab',lambda:page.get_by_role('tab',name='报告导出').click())
        if args.ui_version=='before':
            operation('prepare_all_exports',lambda:page.get_by_role('button',name='准备导出文件').click(),lambda:page.get_by_role('button',name='下载 PDF 报告').wait_for(timeout=180000))
        else:
            for label, name in [('PDF 报告','pdf'),('Excel 报告','excel'),('ZIP 报告包','zip')]:
                operation('generate_'+name,lambda label=label:page.get_by_role('button',name='生成 '+label,exact=True).click(),lambda label=label:page.get_by_role('button',name='下载 '+label).wait_for(timeout=180000))
        t=time.perf_counter();previous=traffic[0];previous_finished=finished[0]
        with page.expect_download() as event:page.get_by_role('button',name='下载 PDF 报告').click()
        target=args.output.parent/f'browser-{args.scale}-{repeat}.pdf';event.value.save_as(target);idle()
        records.append({'repeat':repeat,'name':'pdf_download','seconds':time.perf_counter()-t,'bytes':target.stat().st_size,'received_websocket_bytes':traffic[0]-previous,'script_finished_events':finished[0]-previous_finished})
        page.screenshot(path=str(args.output.parent/f'browser-{args.scale}-{repeat}.png'),full_page=True)
        records.append({'repeat':repeat,'name':'browser_health','page_errors':errors,'long_tasks_ms':page.evaluate('window.__longTasks')})
        assert not errors;context.close()
    browser.close()
summary={name:{'median':statistics.median(x['seconds'] for x in records if x['name']==name),'min':min(x['seconds'] for x in records if x['name']==name),'max':max(x['seconds'] for x in records if x['name']==name)} for name in {x['name'] for x in records if 'seconds'in x}}
args.output.write_text(json.dumps({'method':'fresh browser context, same warm server; perf_counter click to first script_finished recorded separately; complete-operation required UI controls/visible Plotly + idle + two animation frames; 20ms event polling; websocket payload bytes, not HTTP transfer size','scale':args.scale,'ui_version':args.ui_version,'chrome_version':browser.version,'records':records,'summary':summary},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
