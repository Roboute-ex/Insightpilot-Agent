"""Real isolated Chrome UI checks; no user browser profile or network data upload."""
import argparse,json,re,time
from pathlib import Path
from playwright.sync_api import sync_playwright
from streamlit.proto.ForwardMsg_pb2 import ForwardMsg
p=argparse.ArgumentParser();p.add_argument('--url',default='http://127.0.0.1:8506');p.add_argument('--output',type=Path,required=True);a=p.parse_args()
a.output.mkdir(parents=True,exist_ok=True);records=[];errors=[]
print('starting playwright',flush=True)
with sync_playwright() as pw:
    print('launching Chrome',flush=True)
    browser=pw.chromium.launch(executable_path=r'C:\Program Files\Google\Chrome\Application\chrome.exe',headless=True,chromium_sandbox=True)
    print('Chrome ready',flush=True)
    context=browser.new_context(viewport={'width':1500,'height':1060},accept_downloads=True)
    page=context.new_page();finished=[0]
    page.on('pageerror',lambda e:errors.append(str(e)))
    def frame(data):
        if isinstance(data,bytes):
            m=ForwardMsg()
            try:m.ParseFromString(data)
            except Exception:return
            if m.WhichOneof('type')=='script_finished' and m.script_finished in (0,3):finished[0]+=1
    page.on('websocket',lambda w:w.on('framereceived',frame))
    def idle():
        page.locator('[data-testid="stStatusWidget"]').wait_for(state='hidden',timeout=120000)
        page.evaluate('()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')
    def act(fn):
        print('ui action',flush=True)
        n=finished[0];fn();deadline=time.monotonic()+120
        while finished[0]<=n:
            if time.monotonic()>deadline:raise TimeoutError('script completion')
            page.wait_for_timeout(30)
        idle()
    def click(label):act(lambda:page.get_by_role('button',name=label,exact=(label!='开始分析')).click())
    def combo(label,value):
        def action():
            box=page.get_by_role('combobox',name=label,exact=True)
            box.fill(value);box.press('ArrowDown');box.press('Enter')
        act(action)
    def save(name):
        print('capture '+name,flush=True)
        page.screenshot(path=str(a.output/(name+'.png')),full_page=True)
        (a.output/(name+'.txt')).write_text(page.locator('body').inner_text(),encoding='utf-8')
    def current_run():return page.get_by_text(re.compile('当前选定运行')).inner_text()
    def analyze():
        old=current_run() if page.get_by_text(re.compile('当前选定运行')).count() else None
        click('开始分析');deadline=time.monotonic()+120
        while not page.get_by_text(re.compile('当前选定运行')).count() or current_run()==old:
            if time.monotonic()>deadline:raise TimeoutError('new completed run')
            page.wait_for_timeout(100)
        idle()
    try:
        print('navigation '+a.url,flush=True)
        page.goto(a.url,wait_until='domcontentloaded');print('DOM loaded',flush=True);page.get_by_role('button',name='开始分析').wait_for(timeout=30000);idle()
        analyze();save('overview')
        act(lambda:page.get_by_text('专业分析',exact=True).click())
        act(lambda:page.get_by_text('指标口径',exact=True).click())
        page.locator('.ip-summary-card').first.scroll_into_view_if_needed();save('metric-card')
        fonts=page.locator('.ip-summary-card').first.evaluate("e=>({title:getComputedStyle(e.querySelector('.ip-summary-title')).fontSize,body:getComputedStyle(e.querySelector('.ip-summary-content')).fontSize})")
        assert fonts=={'title':'16px','body':'14px'}
        records.append({'check':'12pt_10_5pt_card','passed':True,**fonts})
        act(lambda:page.get_by_role('tab',name='质量检查',exact=True).click());page.get_by_text('分析质量检查',exact=True).scroll_into_view_if_needed();save('quality')
        act(lambda:page.get_by_text('修改维度、基准或比较两次分析',exact=True).click())
        combo('分支维度','city');click('修改维度重新分析');analyze();city=current_run();save('city-branch')
        click('返回上一步');assert '结果已释放' in page.locator('body').inner_text()
        if page.get_by_role('combobox',name='分支维度',exact=True).count()==0:act(lambda:page.get_by_text('修改维度、基准或比较两次分析',exact=True).click())
        combo('分支维度','channel');click('修改维度重新分析');analyze();channel=current_run()
        if page.get_by_role('combobox',name='与另一条分析比较',exact=True).count()==0:act(lambda:page.get_by_text('修改维度、基准或比较两次分析',exact=True).click())
        def compare():
            box=page.get_by_role('combobox',name='与另一条分析比较',exact=True)
            needle=re.search(r'运行 ([a-f0-9-]+)',city).group(1)[:8]
            box.fill(needle);box.press('ArrowDown')
            print('compare options',page.get_by_role('option').all_text_contents(),flush=True)
            page.get_by_role('option').filter(has_text=needle).click()
        act(compare);assert '维度不同' in page.locator('body').inner_text();page.get_by_text('可比性检查',exact=True).scroll_into_view_if_needed();save('branch-comparison')
        records.append({'check':'city_channel_branch_and_released_parent','passed':True,'city':city,'channel':channel})
        act(lambda:page.get_by_role('tab',name='报告导出',exact=True).click())
        for label in ('PDF 报告','Excel 报告','ZIP 报告包'):
            click('生成 '+label)
            with page.expect_download() as event:page.get_by_role('button',name='下载 '+label).click()
            target=a.output/event.value.suggested_filename;event.value.save_as(target)
            records.append({'check':'selected_run_download','format':label,'bytes':target.stat().st_size,'run':channel})
        save('exports')
        assert not errors
        records.append({'check':'browser_console','passed':True,'errors':errors})
    except Exception:
        save('failure');raise
    finally:
        a.output.joinpath('checks.json').write_text(json.dumps({'browser':browser.version,'records':records,'page_errors':errors},ensure_ascii=False,indent=2),encoding='utf-8')
        context.close();browser.close()
