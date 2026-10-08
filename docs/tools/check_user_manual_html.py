"""Read only the generated local HTML in isolated Chrome; never opens the app."""
from pathlib import Path
import argparse,json,re,hashlib
from playwright.sync_api import sync_playwright

p=argparse.ArgumentParser();p.add_argument('--html',type=Path,required=True);p.add_argument('--output-dir',type=Path,required=True);args=p.parse_args()
path=args.html.resolve();out=args.output_dir.resolve();out.mkdir(parents=True,exist_ok=True)
raw=path.read_text(encoding='utf-8')
assert '<meta charset="utf-8">' in raw
assert not re.search(r'<script\b|<link[^>]+(?:stylesheet|preload)|(?:src|url)\s*[=(]\s*["\']?https?://',raw,re.I)
record={'file':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'isolated_chrome':True,'network_requests':[],'page_errors':[],'checks':{},'screenshots':[]}
with sync_playwright() as tool:
 browser=tool.chromium.launch(executable_path=r'C:\Program Files\Google\Chrome\Application\chrome.exe',headless=True,chromium_sandbox=True)
 context=browser.new_context(viewport={'width':1440,'height':1000},accept_downloads=True,service_workers='block')
 context.set_offline(True);page=context.new_page()
 page.on('request',lambda req:record['network_requests'].append(req.url) if req.url.startswith(('http://','https://')) else None)
 page.on('pageerror',lambda err:record['page_errors'].append(str(err)))
 page.goto(path.as_uri(),wait_until='load');record['chrome']=browser.version
 record['checks']['chinese_text_searchable']='轻量因果探索' in page.locator('main').inner_text()
 record['checks']['all_images_loaded']=page.locator('main img').evaluate_all('(items)=>items.every(e=>e.complete&&e.naturalWidth>0)')
 record['checks']['all_images_inline']=page.locator('main img').evaluate_all('(items)=>items.every(e=>e.src.startsWith("data:image/"))')
 record['checks']['all_internal_targets_exist']=page.locator('a[href^="#"]').evaluate_all('(items)=>items.every(e=>document.getElementById(e.getAttribute("href").slice(1)))')
 record['images']=page.locator('main img').count();record['toc_entries']=page.locator('nav a').count()
 first=page.locator('nav a').first;href=first.get_attribute('href');first.click();record['checks']['toc_actual_click']=page.evaluate('location.hash')==href
 page.evaluate('window.scrollTo(0,0)')
 for width in (1440,1024,760):
  page.set_viewport_size({'width':width,'height':1000});page.screenshot(path=str(out/f'html-{width}.png'),full_page=False)
  record['screenshots'].append(f'html-{width}.png')
  record['checks'][f'no_horizontal_overflow_{width}']=page.evaluate('document.documentElement.scrollWidth<=innerWidth')
 csvlinks=page.locator('a[download$=".csv"]')
 record['checks']['teaching_csv_embedded']=csvlinks.count()>=2
 record['downloads']=[]
 seen=set()
 for i in range(csvlinks.count()):
  link=csvlinks.nth(i);name=link.get_attribute('download')
  if name in seen:continue
  seen.add(name)
  with page.expect_download() as event:link.click()
  downloaded=out/name;event.value.save_as(downloaded)
  original=Path(__file__).resolve().parents[1]/'examples/user_manual'/name
  same=downloaded.read_bytes()==original.read_bytes();record['downloads'].append({'file':name,'matches_source':same})
  record['checks']['csv_download_'+name]=same
 context.close();browser.close()
record['checks']['no_external_requests']=not record['network_requests'];record['checks']['no_page_errors']=not record['page_errors']
(out/'html-validation.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(record,ensure_ascii=False,indent=2))
assert all(record['checks'].values()),'See html-validation.json'
