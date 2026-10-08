"""Real Chrome checks for background responsiveness, cooperative cancel and source races."""
import argparse,json,time,re
from pathlib import Path
from playwright.sync_api import sync_playwright
from streamlit.proto.ForwardMsg_pb2 import ForwardMsg
p=argparse.ArgumentParser();p.add_argument('--url',default='http://127.0.0.1:8503');p.add_argument('--output',type=Path,required=True);args=p.parse_args()
args.output.parent.mkdir(parents=True,exist_ok=True);records=[];phases=[];errors=[]
with sync_playwright() as pw:
    browser=pw.chromium.launch(executable_path=r'C:\Program Files\Google\Chrome\Application\chrome.exe',headless=True,chromium_sandbox=True)
    context=browser.new_context(viewport={'width':1500,'height':1060});page=context.new_page();finished=[0]
    page.on('pageerror',lambda error:errors.append(str(error)))
    def received(frame):
        if not isinstance(frame,bytes):return
        msg=ForwardMsg()
        try:msg.ParseFromString(frame)
        except Exception:return
        kind=msg.WhichOneof('type')
        if kind=='script_finished' and msg.script_finished in (0,3):finished[0]+=1
        if kind=='delta' and msg.delta.WhichOneof('type')=='new_element':
            el=msg.delta.new_element
            if el.WhichOneof('type')=='markdown' and '当前任务：' in el.markdown.body:
                phases.append(el.markdown.body)
    page.on('websocket',lambda ws:ws.on('framereceived',received))
    def idle():
        page.locator('[data-testid="stStatusWidget"]').wait_for(state='hidden',timeout=60000)
        page.evaluate('()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')
    def response(action):
        previous=finished[0];t=time.perf_counter();action();deadline=t+60
        while finished[0]<=previous:
            if time.perf_counter()>deadline:raise TimeoutError('No completed UI response')
            page.wait_for_timeout(20)
        idle();return time.perf_counter()-t
    def scale(label):
        control=page.get_by_role('combobox',name='数据规模',exact=True)
        control.fill(label);control.press('ArrowDown')
        page.get_by_role('option',name=label,exact=True).click()
    def ready():
        page.get_by_role('button',name=re.compile('开始分析')).wait_for(timeout=120000);idle()
    def running():
        page.get_by_role('button',name=re.compile('取消当前任务')).wait_for(timeout=60000)
    def save(name):
        page.screenshot(path=str(args.output.parent/(name+'.png')),full_page=True)
        (args.output.parent/(name+'.txt')).write_text(page.locator('body').inner_text(),encoding='utf-8')
    try:
        page.goto(args.url,wait_until='domcontentloaded');ready()
        response(lambda:page.get_by_text('数据设置',exact=True).click())
        # Data management is a presentation-only native expander; opening it does
        # not submit any task. Keep its controls accessible during source work.
        page.get_by_text('数据管理',exact=True).click()
        response(lambda:scale('大型'));running()
        response(lambda:page.get_by_text('数据设置',exact=True).click())
        running()
        seconds=response(lambda:page.get_by_text('数据设置',exact=True).click())
        assert seconds<3.0,'Advanced data settings remained blocked during source preparation'
        save('running-settings-change')
        records.append({'check':'advanced_data_settings_during_real_large_preparation','response_seconds':seconds,'passed':True})
        response(lambda:scale('小型'));ready()
        assert '小型模拟数据' in page.locator('body').inner_text()
        page.wait_for_timeout(1500)
        assert '小型模拟数据' in page.locator('body').inner_text()
        assert page.get_by_role('button',name=re.compile('生成 PDF 报告')).count()==0
        assert page.get_by_text('执行摘要',exact=True).count()==0
        records.append({'check':'large_to_small_while_running_no_stale_source_adoption','passed':True})
        response(lambda:scale('大型'));running()
        seconds=response(lambda:page.get_by_role('button',name=re.compile('取消当前任务')).click())
        page.get_by_text('当前任务：已取消',exact=True).wait_for(timeout=60000);idle()
        assert page.get_by_role('button',name=re.compile('开始分析')).count()==0
        assert page.get_by_role('button',name=re.compile('生成 PDF 报告')).count()==0
        assert page.get_by_text('执行摘要',exact=True).count()==0
        save('cancelled-source')
        records.append({'check':'cancel_large_preparation_no_result_or_auto_restart','request_response_seconds':seconds,'passed':True})
        response(lambda:page.get_by_role('button',name='加载 / 刷新当前数据',exact=False).click());ready()
        records.append({'check':'explicit_refresh_after_cancel_runs_again','passed':True})
        seconds=response(lambda:page.get_by_role('button',name=re.compile('开始分析')).click());running()
        records.append({'check':'analysis_submit_returns_while_worker_active','submit_response_seconds':seconds,'passed':True})
        seconds=response(lambda:page.get_by_role('button',name=re.compile('释放本会话数据与结果')).click())
        page.get_by_text('本会话数据与结果引用已释放。',exact=False).wait_for(timeout=60000);idle()
        assert page.get_by_role('button',name=re.compile('开始分析')).count()==0
        assert page.get_by_role('button',name=re.compile('生成 PDF 报告')).count()==0
        assert page.get_by_text('执行摘要',exact=True).count()==0
        save('released-session')
        records.append({'check':'release_during_analysis_discards_late_result','response_seconds':seconds,'passed':True})
        assert len(set(phases))>=3,'Real execution stages were not observed'
        assert not errors
    except Exception as exc:
        runner_error=type(exc).__name__+': '+str(exc)
        save('failure')
        args.output.write_text(json.dumps({'passed':False,'records':records,'phases':phases,'page_errors':errors,'runner_error':runner_error},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        raise
    finally:
        context.close();browser.close()
args.output.write_text(json.dumps({'passed':True,'method':'real Chrome with actual built-in large source and analysis, no injected delays; UI response is script_finished plus paint, not task completion','records':records,'phases':phases,'page_errors':errors},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'passed':True,'checks':len(records),'observed_stage_messages':len(set(phases))}))
