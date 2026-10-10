"""Real Chrome method catalog/causal acceptance using UI actions and uploaded synthetic CSV."""
from __future__ import annotations
import argparse,csv,json,urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright
from check_workbench_browser import BrowserProbe


def main():
 p=argparse.ArgumentParser();p.add_argument('--url',required=True);p.add_argument('--output',type=Path,required=True);args=p.parse_args()
 args.output.mkdir(parents=True,exist_ok=False)
 fixture=args.output/'causal_fixture.csv'
 with fixture.open('w',newline='',encoding='utf-8') as f:
  writer=csv.DictWriter(f,fieldnames=['date','group','outcome','covariate']);writer.writeheader()
  for group in ['control','treatment']:
   for x in range(12):writer.writerow({'date':f'2026-09-{x+1:02d}','group':group,'outcome':10+x+(2 if group=='treatment' else 0)+(0.25 if x%2 else -0.25),'covariate':x})
 record={'url':args.url,'health_status':urllib.request.urlopen(args.url+'/_stcore/health').status,'checks':{},'operations':[],
         'fixture':{'rows':24,'control_rows':12,'treatment_rows':12,'expected_naive_difference':2,'expected_adjusted_effect':2,'formula':'10 + x + 2*treated + alternating +/-0.25; both groups share x=0..11'}}
 with sync_playwright() as pw:
  browser=pw.chromium.launch(executable_path=r'C:\Program Files\Google\Chrome\Application\chrome.exe',headless=True,chromium_sandbox=True)
  record['chrome']=browser.version;probe=BrowserProbe(browser,args.output,record);page=None
  errors=probe.errors
  def start_session():
   nonlocal page
   probe.session(args.url);page=probe.page
  def idle():probe.idle()
  def action(name,fn,wait=True):probe.action(name,fn,wait=wait)
  def click(label):probe.click(label)
  def expand(label):action(label,lambda:page.get_by_text(label,exact=True).click())
  def choose(label,value,wait=True):probe.choose(label,value,wait=wait)
  def question(value):probe.question(value)
  def capture(name):probe.capture(name)
  def body():return probe.body()
  def add_multi(label,value,wait=True):probe.multiselect(label,value,wait=wait)
  try:
   start_session();capture('01-home')
   record['checks']['fresh_catalog_entry']=page.get_by_text('分析方法',exact=True).is_visible()
   record['checks']['no_modes']=not page.get_by_text('简洁演示',exact=True).count()
   question('昨日订单量为什么下降？');expand('分析方法')
   record['catalog_buttons']=page.get_by_role('button',name='配置：').all_text_contents()
   record['checks']['all_ten_visible']=len(record['catalog_buttons'])==10
   page.get_by_role('button',name='配置：轻量因果探索').scroll_into_view_if_needed();capture('02-all-methods-causal')
   click('配置：轻量因果探索')
   page.get_by_text('treatment、control 只是组别取值，不能代替数据表中的分组字段。',exact=False).first.wait_for(timeout=15000)
   record['invalid_body']=body();record['checks']['invalid_start_disabled']=not page.get_by_role('button',name='开始分析').is_enabled()
   record['checks']['invalid_no_false_outcome']='缺少结果变量' not in body()
   record['checks']['invalid_no_failed_task']='当前任务：失败' not in body()
   record['checks']['invalid_no_result']=not page.get_by_text('执行摘要',exact=True).count()
   page.get_by_role('button',name='改用推荐方法').scroll_into_view_if_needed();capture('03-invalid-reason')
   click('改用推荐方法');record['checks']['accept_no_analysis']=not page.get_by_text('执行摘要',exact=True).count()
   click('开始分析');page.get_by_text('执行摘要',exact=True).wait_for(timeout=90000);idle()
   record['checks']['order_run_completed']=page.get_by_text('已完成',exact=True).count()>=1 and all(term in body() for term in ['执行摘要','昨日订单量为','核心指标表现'])
   page.get_by_text('执行摘要',exact=True).scroll_into_view_if_needed();capture('04-order-result')
   start_session();choose('数据来源','上传 CSV / Excel')
   action('upload deterministic 24-row CSV',lambda:page.locator('input[type="file"]').set_input_files(str(fixture)))
   page.get_by_role('textbox',name='你想分析什么？',exact=True).wait_for(timeout=90000);idle()
   question('控制协变量后，处理组与对照组的结果有多大差异？')
   expand('分析方法');click('配置：轻量因果探索');choose('分析目标','轻量因果探索')
   choose('分组字段','不选择');choose('处理字段','group');choose('结果字段','outcome');choose('聚合方式','均值')
   # Mapping uses actual uploaded columns. No session-state or engine/result injection.
   add_multi('指标字段','outcome');add_multi('协变量','covariate');click('确认当前字段映射')
   add_multi('控制变量','covariate',False);choose('处理组值','treatment',False);choose('对照组值','control',False)
   click('应用参数并更新建议')
   record['configured_body']=body();record['checks']['causal_ready']=page.get_by_role('button',name='开始分析').is_enabled()
   page.get_by_role('button',name='开始分析').scroll_into_view_if_needed();capture('05-causal-config-ready')
   click('开始分析');page.get_by_text('执行摘要',exact=True).wait_for(timeout=90000);idle()
   record['checks']['causal_completed']=page.get_by_text('已完成',exact=True).count()>=1 and all(term in body() for term in ['执行摘要','=2.0000','n=24'])
   record['result_body']=body();page.get_by_text('执行摘要',exact=True).evaluate("el=>el.scrollIntoView({block:'start'})");capture('06-causal-result')
   action('result details',lambda:page.get_by_text('明细',exact=True).click());choose('选择结果明细表','adjusted_effect_summary');record['details_body']=body();capture('07-causal-details')
   action('report navigation',lambda:page.get_by_text('报告',exact=True).click())
   record['export_generators']=[v.strip() for v in page.get_by_role('button').all_text_contents() if v.strip().startswith('生成')]
   record['checks']['six_formats_pdf_first']=record['export_generators']==['生成 PDF 报告','生成 Markdown 报告','生成 HTML 报告','生成 Excel 报告','生成 运行清单 JSON','生成 ZIP 报告包']
   record['checks']['lazy_exports']=page.get_by_role('button',name='下载 PDF 报告').count()==0
   for label,kind in [('PDF 报告','pdf'),('Excel 报告','xlsx'),('ZIP 报告包','zip')]:
    click('生成 '+label)
    with page.expect_download() as download:page.get_by_role('button',name='下载 '+label).click()
    path=args.output/('causal-selected-run.'+kind);download.value.save_as(path);record['checks']['download_'+kind]=path.stat().st_size>0
   from openpyxl import load_workbook
   from pypdf import PdfReader
   workbook=load_workbook(args.output/'causal-selected-run.xlsx',read_only=True,data_only=True)
   record['excel']={sheet.title:list(sheet.values) for sheet in workbook};workbook.close()
   pdf=PdfReader(args.output/'causal-selected-run.pdf');record['pdf_text']='\n'.join(p.extract_text() or '' for p in pdf.pages)
   record['checks']['pdf_causal_caveats']=all(term in record['pdf_text'] for term in ['无未观测混杂','重叠性','此结果不是因果证明'])
   result_rows=record['excel']['结果_adjusted_effect_summary'];actual=dict(zip(result_rows[0],result_rows[1]))
   record['actual_result']=actual
   # Expected difference=2 follows directly from the independently constructed paired groups.
   record['checks']['excel_naive_2']=abs(float(actual['naive_difference'])-2)<1e-10
   record['checks']['excel_adjusted_2']=abs(float(actual['adjusted_effect'])-2)<1e-10
   record['checks']['excel_n_24']=actual['样本量']==24
   record['checks']['actual_covariate_used']=actual['covariates']=="['covariate']" and actual['计算方法']=='ordinary_least_squares_regression_adjustment'
   record['checks']['summary_has_actual_numbers']=all(t in record['result_body'] for t in ['=2.0000','n=24','此结果不是因果证明'])
   record['checks']['pdf_has_actual_numbers']=all(t in record['pdf_text'] for t in ['=2.0000','n=24','adjusted_effect_summary'])
   import zipfile
   with zipfile.ZipFile(args.output/'causal-selected-run.zip') as bundle:
    record['checks']['zip_pdf_matches']=bundle.read(next(n for n in bundle.namelist() if n.endswith('report.pdf')))==(args.output/'causal-selected-run.pdf').read_bytes()
   record['checks']['same_run_excel_pdf']=dict(record['excel']['执行摘要'][1:])['运行编号'] in record['pdf_text']
   capture('08-causal-exports');record['page_errors']=errors;assert not errors
   assert all(record['checks'].values()),record['checks']
  except Exception as exc:
   record['error']=str(exc)
   if page is not None:record['failure_body']=body();capture('failure')
   raise
  finally:
   (args.output/'checks.json').write_text(json.dumps(record,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8')
   probe.close()
   browser.close()
 print(json.dumps(record['checks'],ensure_ascii=False));return 0
if __name__=='__main__':raise SystemExit(main())
