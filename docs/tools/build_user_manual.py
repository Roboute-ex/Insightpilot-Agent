"""Build documentation only, from Markdown; never imports the application."""
from __future__ import annotations
import argparse, base64, hashlib, html, json, re
from pathlib import Path
from urllib.parse import unquote
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer,
    Table, TableStyle, Image, PageBreak, KeepTogether, CondPageBreak, Flowable, NextPageTemplate)
from reportlab.platypus.tableofcontents import TableOfContents
from PIL import Image as PILImage
from pypdf import PdfReader

DOCS = Path(__file__).resolve().parents[1]
ROOT = DOCS.parent
NAMES = {'html':'InsightPilot_Agent_使用手册_0.1.0.html',
         'manual':'InsightPilot_Agent_使用手册_0.1.0.pdf',
         'quick':'InsightPilot_Agent_日常操作速查卡_0.1.0.pdf'}
LINK = re.compile(r'(!?)\[([^\]]+)\]\(([^)]+)\)')


def parse(text):
    lines=text.splitlines(); blocks=[]; i=0; anchor=None
    while i<len(lines):
        line=lines[i].strip()
        if not line: i+=1; continue
        a=re.fullmatch(r'<a\s+id=["\']([^"\']+)["\']\s*>\s*</a>',line)
        if a: anchor=a.group(1); i+=1; continue
        if line.startswith(('```','~~~')):
            fence=line[:3];language=line[3:]; chunk=[]; i+=1
            while i<len(lines) and not lines[i].strip().startswith(fence):
                chunk.append(lines[i]);i+=1
            blocks.append(('code','\n'.join(chunk),language)); i+=1; continue
        heading=re.match(r'^(#{1,6})\s+(.+)',line)
        if heading:
            level=len(heading.group(1)); title=heading.group(2)
            blocks.append(('heading',title,level,anchor or f'section-{len(blocks)}'));anchor=None;i+=1;continue
        picture=re.fullmatch(r'!\[([^\]]*)\]\(([^)]+)\)',line)
        if picture: blocks.append(('image',picture.group(1),picture.group(2)));i+=1;continue
        if line.startswith('|') and i+1<len(lines) and re.match(r'^\|?[\s:|-]+\|?$',lines[i+1].strip()):
            rows=[]
            while i<len(lines) and lines[i].strip().startswith('|'):
                value=lines[i].strip()
                if not re.match(r'^\|?[\s:|-]+\|?$',value): rows.append([c.strip().replace('\\|','|') for c in re.split(r'(?<!\\)\|',value.strip('|'))])
                i+=1
            blocks.append(('table',rows));continue
        if re.match(r'^([-*+]\s+|\d+[.)]\s+)',line):
            blocks.append(('item',line));i+=1;continue
        if line.startswith('>'):
            blocks.append(('quote',line.lstrip('> ')));i+=1;continue
        if line in ('---','***'): i+=1;continue
        paragraph=[line];i+=1
        while i<len(lines) and lines[i].strip() and not re.match(r'^(#|```|~~~|\||!\[|<a |>|[-*+]\s|\d+[.)]\s)',lines[i].strip()):
            paragraph.append(lines[i].strip());i+=1
        blocks.append(('paragraph',' '.join(paragraph)))
    return blocks


def without_toc(blocks):
    result=[]; skip=False
    for b in blocks:
        if b[0]=='heading':
            if b[1].strip() in ('目录','阅读目录'):skip=True;continue
            if skip and b[2]<=2:skip=False
        if not skip:result.append(b)
    return result


def local_path(url):
    return (DOCS/unquote(url.strip('<>')).split('#')[0]).resolve()


def html_inline(value):
    tokens={}
    def protect(content):
        key=f'ZZTOKEN{len(tokens)}ZZ';tokens[key]=content;return key
    def link(m):
        image,label,url=m.groups(); url=url.strip('<>')
        if image:
            path=local_path(url);data=base64.b64encode(path.read_bytes()).decode()
            return protect(f'<img alt="{html.escape(label)}" src="data:image/png;base64,{data}">')
        extra=''
        if not url.startswith(('#','http:','https:','mailto:')):
            path=local_path(url)
            if path.suffix.lower()=='.csv':
                url='data:text/csv;charset=utf-8;base64,'+base64.b64encode(path.read_bytes()).decode();extra=f' download="{html.escape(path.name)}"'
            elif path.is_file():
                url='data:text/plain;charset=utf-8;base64,'+base64.b64encode(path.read_bytes()).decode();extra=f' download="{html.escape(path.name)}"'
        return protect(f'<a href="{html.escape(url,quote=True)}"{extra}>{html.escape(label)}</a>')
    value=LINK.sub(link,value)
    value=re.sub(r'`([^`]+)`',lambda m:protect('<code>'+html.escape(m.group(1))+'</code>'),value)
    value=html.escape(value)
    value=re.sub(r'\*\*(.+?)\*\*',r'<strong>\1</strong>',value)
    for k,v in tokens.items():value=value.replace(k,v)
    return value


def build_html(blocks,target,source_hash):
    title=next(b[1] for b in blocks if b[0]=='heading' and b[2]==1)
    navigation=''.join(f'<a href="#{b[3]}">{html.escape(b[1])}</a>' for b in blocks if b[0]=='heading' and b[2]==2)
    content=[]
    for b in blocks:
        kind=b[0]
        if kind=='heading':content.append(f'<h{b[2]} id="{b[3]}">{html_inline(b[1])}</h{b[2]}>')
        elif kind=='image':content.append(f'<figure>{html_inline("!["+b[1]+"]("+b[2]+")")}<figcaption>{html.escape(b[1])}。可放大查看原始模拟界面。</figcaption></figure>')
        elif kind=='code':content.append('<pre><code>'+html.escape(b[1])+'</code></pre>')
        elif kind=='table':
            rows=b[1];markup='<thead><tr>'+''.join('<th>'+html_inline(c)+'</th>' for c in rows[0])+'</tr></thead><tbody>'
            markup+=''.join('<tr>'+''.join('<td>'+html_inline(c)+'</td>' for c in row)+'</tr>' for row in rows[1:])+'</tbody>'
            content.append('<div class="table-wrap"><table>'+markup+'</table></div>')
        elif kind=='quote':content.append('<aside>'+html_inline(b[1])+'</aside>')
        else:content.append('<p'+(' class="step"' if kind=='item' else '')+'>'+html_inline(b[1])+'</p>')
    css='''*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:#f4f7f7;color:#18302e;font-family:"Microsoft YaHei","Noto Sans CJK SC",sans-serif;font-size:16px;line-height:1.8}nav{position:fixed;width:265px;top:0;bottom:0;overflow:auto;padding:28px 22px;background:#e8f0ef;border-right:1px solid #cadbd7}nav strong{display:block;margin-bottom:18px}nav a{display:block;padding:5px 0;color:#205e57;text-decoration:none;font-size:14px}main{max-width:1040px;margin-left:265px;padding:40px 48px;background:white;min-height:100vh}h1{font-size:28px;margin-top:0}h2{font-size:23px;border-bottom:1px solid #cbdcda;padding-bottom:9px;margin-top:46px;scroll-margin-top:22px}h3{font-size:19px;margin-top:30px}h4{font-size:17px}a{color:#08766d}p{margin:10px 0}aside{border-left:4px solid #38887b;background:#edf6f2;padding:10px 16px}code{font-family:Consolas,"Microsoft YaHei",monospace;font-size:.94em;overflow-wrap:anywhere}pre{white-space:pre-wrap;overflow-wrap:anywhere;padding:15px;background:#f1f5f5;border:1px solid #d5dfdd;border-radius:5px;line-height:1.6}.table-wrap{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:14px;margin:16px 0}th,td{text-align:left;vertical-align:top;border:1px solid #ccd9d7;padding:8px 10px;overflow-wrap:anywhere}th{background:#edf5f3}figure{margin:25px 0}figure img{width:100%;height:auto;border:1px solid #c9d9d5}figcaption{font-size:14px;color:#4c6963;padding-top:7px}.step{padding-left:8px}.footer{font-size:13px;color:#4c6963;margin-top:40px}@media(max-width:850px){nav{position:static;width:auto;max-height:none}main{margin:0;padding:24px 18px}h1{font-size:24px}}@media print{@page{size:A4;margin:18mm}body{background:white;font-size:10.5pt;line-height:1.65}nav{position:static;width:auto;page-break-after:always}main{margin:0;padding:0;max-width:none}h2,h3{break-after:avoid}pre,tr,figure{break-inside:avoid}thead{display:table-header-group}a{color:inherit}figure img{max-height:190mm;object-fit:contain}.table-wrap{overflow:visible}}'''
    document=f'<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="manual-source-sha256" content="{source_hash}"><title>{html.escape(title)}</title><style>{css}</style></head><body><nav id="contents" aria-label="手册目录"><strong>InsightPilot Agent 0.1.0<br>日常使用手册</strong>{navigation}</nav><main>'+''.join(content)+'<p class="footer">文档日期：2026-09-30。图片与CSV均为合成教学数据；本文件无需网络、账号或外部字体。</p></main></body></html>'
    target.write_text(document,encoding='utf-8')


def pdf_inline(value,anchors):
    tokens={}
    def token(v):k=f'ZZTOKEN{len(tokens)}ZZ';tokens[k]=v;return k
    def link(m):
        _,label,url=m.groups();url=url.strip('<>')
        if url.startswith('#') and url[1:] in anchors:return token(f'<link href="{html.escape(url,quote=True)}" color="#08766d">{html.escape(label)}</link>')
        if url.startswith(('http:','https:')):return token(f'<link href="{html.escape(url,quote=True)}" color="#08766d">{html.escape(label)}</link>')
        return token(html.escape(label))
    value=LINK.sub(link,value)
    value=re.sub(r'`([^`]+)`',lambda m:token('<font color="#235f57">'+html.escape(m.group(1))+'</font>'),value)
    value=html.escape(value)
    value=re.sub(r'\*\*(.+?)\*\*',r'<b>\1</b>',value)
    for k,v in tokens.items():value=value.replace(k,v)
    return value


class ScreenshotClip(Flowable):
    """Crop only the PDF display window; embed the unchanged original screenshot."""
    def __init__(self,path,bbox,scale):
        super().__init__();self.path=path;self.bbox=bbox;self.scale=scale
        self.width=(bbox[2]-bbox[0])*scale;self.height=(bbox[3]-bbox[1])*scale
    def draw(self):
        x0,y0,x1,y1=self.bbox;w,h=PILImage.open(self.path).size;c=self.canv
        c.saveState();clip=c.beginPath();clip.rect(0,0,self.width,self.height);c.clipPath(clip,stroke=0)
        c.drawImage(ImageReader(str(self.path)),-x0*self.scale,-(h-y1)*self.scale,width=w*self.scale,height=h*self.scale)
        c.restoreState()

class ManualDoc(BaseDocTemplate):
    def __init__(self,filename,**kwargs):
        super().__init__(filename,pagesize=A4,leftMargin=19*mm,rightMargin=19*mm,topMargin=20*mm,bottomMargin=18*mm,**kwargs)
        frame=Frame(self.leftMargin,self.bottomMargin,self.width,self.height,id='body',leftPadding=0,rightPadding=0,topPadding=0,bottomPadding=0)
        wide=landscape(A4); wide_frame=Frame(19*mm,18*mm,wide[0]-38*mm,wide[1]-38*mm,id='wide',leftPadding=0,rightPadding=0,topPadding=0,bottomPadding=0)
        self.addPageTemplates([PageTemplate(id='body',frames=frame,onPage=self.page_decoration,pagesize=A4),PageTemplate(id='wide',frames=wide_frame,onPage=self.page_decoration,pagesize=wide)])
    def page_decoration(self,canvas,doc):
        canvas.saveState();canvas.setFont('ManualCN',8.5);canvas.setFillColor(colors.HexColor('#57736c'))
        canvas.drawString(self.leftMargin,canvas._pagesize[1]-12*mm,'InsightPilot Agent 0.1.0 · 日常使用')
        canvas.drawRightString(canvas._pagesize[0]-self.rightMargin,10*mm,str(doc.page));canvas.restoreState()
    def afterFlowable(self,flowable):
        if isinstance(flowable,Paragraph) and hasattr(flowable,'manual_anchor'):
            key=flowable.manual_anchor;level=flowable.manual_level;text=flowable.getPlainText()
            self.canv.bookmarkPage(key)
            if level in (2,3):self.canv.addOutlineEntry(text,key,level-2,False)
            if level==2:self.notify('TOCEntry',(0,text,self.page,key))


def styles():
    font='ManualCN';black=colors.HexColor('#18302e')
    base=dict(fontName=font,fontSize=10.5,leading=17,wordWrap='CJK',textColor=black,spaceAfter=6,allowWidows=0,allowOrphans=0)
    s={'body':ParagraphStyle('body',**base)}
    for name,size,leading in [('h1',21,30),('h2',14,22),('h3',12,19),('h4',11,18)]:
        s[name]=ParagraphStyle(name,parent=s['body'],fontName='ManualCN-Bold',fontSize=size,leading=leading,spaceBefore=10,spaceAfter=9,keepWithNext=True)
    s['cell']=ParagraphStyle('cell',parent=s['body'],fontSize=10,leading=15,spaceAfter=0)
    s['headcell']=ParagraphStyle('headcell',parent=s['cell'],fontName='ManualCN-Bold')
    s['code']=ParagraphStyle('code',parent=s['body'],fontSize=9.3,leading=14,backColor=colors.HexColor('#f1f5f5'),borderPadding=7,spaceBefore=6,spaceAfter=12)
    s['quote']=ParagraphStyle('quote',parent=s['body'],leftIndent=9,borderPadding=5,backColor=colors.HexColor('#edf6f2'))
    s['caption']=ParagraphStyle('caption',parent=s['body'],fontSize=9,leading=14,textColor=colors.HexColor('#57736c'))
    return s


def build_pdf(blocks,target,quick=False):
    s=styles()
    if quick:
        # Keep the body at 10.5 pt; a card needs less inter-paragraph whitespace.
        s['body'].leading=15.5;s['body'].spaceAfter=4
        for name in ('h1','h2','h3','h4'):
            s[name].fontSize=16 if name=='h1' else 12
            s[name].leading=23 if name=='h1' else 18
            s[name].spaceBefore=7;s[name].spaceAfter=5
        for name in ('cell','headcell'):
            s[name].fontSize=10.5;s[name].leading=14.5
        s['code'].spaceAfter=7;s['code'].spaceBefore=4
    doc=ManualDoc(str(target),title='InsightPilot Agent 中文日常使用'+('速查卡' if quick else '手册'),author='InsightPilot Agent 本地文档')
    anchors={b[3] for b in blocks if b[0]=='heading'}|{'contents'};story=[];cover=False
    for b in blocks:
        kind=b[0]
        if kind=='heading':
            level=b[2]
            if level==2 and not quick:story.append(CondPageBreak(55*mm))
            p=Paragraph(pdf_inline(b[1],anchors),s.get('h'+str(level),s['h4']));p.manual_anchor=b[3];p.manual_level=level;story.append(p)
            if level==1 and not quick:
                story.append(Paragraph('版本 0.1.0 · 文档核对日期 2026-09-30',s['body']))
                story.append(Paragraph('从第一次订单分析到自有数据、因果探索、透视与报告保存。所有图片和教学CSV均来自已核对的合成验收资料。',s['body']))
                story.append(Spacer(1,7*mm));toc_title=Paragraph('目录',s['h2']);toc_title.manual_anchor='contents';toc_title.manual_level=0;story.append(toc_title)
                toc=TableOfContents();toc.levelStyles=[ParagraphStyle('toc',parent=s['body'],fontSize=10.5,leading=20,rightIndent=20)]
                story.append(toc);story.append(PageBreak());cover=True
        elif kind=='image':
            path=local_path(b[2]);original_size=PILImage.open(path).size
            boxes=json.loads((DOCS/'tools/manual_images.json').read_text(encoding='utf-8'))
            bbox=boxes.get(path.name,{}).get('bbox',[0,0,*original_size])
            wide=landscape(A4); maxw=wide[0]-38*mm; maxh=wide[1]-58*mm
            w,h=bbox[2]-bbox[0],bbox[3]-bbox[1];factor=min(maxw/w,maxh/h)
            im=ScreenshotClip(path,bbox,factor);im.hAlign='LEFT'
            story.extend([NextPageTemplate('wide'),PageBreak(),im,Spacer(1,3*mm),Paragraph(pdf_inline(b[1],anchors)+'（原始模拟截图的主内容区域；图片数字与控件未改，完整图见HTML）',s['caption']),NextPageTemplate('body'),PageBreak()])
        elif kind=='code':
            # CJK wrapping preserves every code character, including long PowerShell paths.
            escaped=html.escape(b[1]).replace(' ','&#160;').replace('\n','<br/>')
            story.append(Paragraph(escaped,s['code']))
        elif kind=='table':
            rows=b[1];count=max(len(r) for r in rows);widths=[doc.width/count]*count
            if count==2:widths=[doc.width*.32,doc.width*.68]
            if count==3:widths=[doc.width*.24,doc.width*.36,doc.width*.40]
            if count==6 and rows[0][0]=='row_group':
                minimum=[pdfmetrics.stringWidth(c,'ManualCN-Bold',s['headcell'].fontSize)+16 for c in rows[0]]
                spare=(doc.width-sum(minimum))/count
                if spare>=0:widths=[v+spare for v in minimum]
            if count==4 and rows[0][0]=='口径与填写':
                widths=[doc.width*.4]+[doc.width*.2]*3
            cells=[[Paragraph(pdf_inline(c,anchors),s['headcell'] if ri==0 else s['cell']) for c in row]+['']*(count-len(row)) for ri,row in enumerate(rows)]
            table=Table(cells,colWidths=widths,repeatRows=1,hAlign='LEFT')
            table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#e8f2ef')),('GRID',(0,0),(-1,-1),.4,colors.HexColor('#c7d9d3')),('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),6),('RIGHTPADDING',(0,0),(-1,-1),6),('TOPPADDING',(0,0),(-1,-1),3.5 if quick else 5),('BOTTOMPADDING',(0,0),(-1,-1),3.5 if quick else 5)]))
            story.extend([table,Spacer(1,3*mm)])
        else:story.append(Paragraph(pdf_inline(b[1],anchors),s['quote'] if kind=='quote' else s['body']))
    doc.multiBuild(story)


def check_markdown(path):
    text=path.read_text(encoding='utf-8'); anchors=set(re.findall(r'<a\s+id=["\']([^"\']+)',text));errors=[]
    if text.count('```')%2 or text.count('~~~')%2:errors.append('unclosed_code_fence')
    if not text.endswith('\n'):errors.append('missing_final_newline')
    refs=[]
    for m in LINK.finditer(text):
        url=m[3].strip('<>');refs.append(url)
        if url.startswith('#') and url[1:] not in anchors:errors.append('missing_anchor:'+url)
        elif not url.startswith(('#','http:','https:','mailto:')) and not local_path(url).is_file():errors.append('missing_file:'+url)
    return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'links':refs,'errors':errors}


def main():
    p=argparse.ArgumentParser();p.add_argument('--output-dir',required=True,type=Path);p.add_argument('--replace-generated',action='store_true');args=p.parse_args()
    out=args.output_dir.resolve();out.mkdir(parents=True,exist_ok=True)
    for n in NAMES.values():
        if (out/n).exists() and not args.replace_generated:raise SystemExit('目标已存在；不覆盖旧交付：'+n)
    pdfmetrics.registerFont(TTFont('ManualCN',r'C:\Windows\Fonts\msyh.ttc',subfontIndex=0))
    pdfmetrics.registerFont(TTFont('ManualCN-Bold',r'C:\Windows\Fonts\msyhbd.ttc',subfontIndex=0))
    pdfmetrics.registerFontFamily('ManualCN',normal='ManualCN',bold='ManualCN-Bold',italic='ManualCN',boldItalic='ManualCN-Bold')
    checks=[check_markdown(DOCS/name) for name in ('user_manual.md','quick_reference.md')]
    if any(c['errors'] for c in checks):raise SystemExit(json.dumps(checks,ensure_ascii=False))
    manual=without_toc(parse((DOCS/'user_manual.md').read_text(encoding='utf-8')))
    quick=without_toc(parse((DOCS/'quick_reference.md').read_text(encoding='utf-8')))
    build_html(manual,out/NAMES['html'],checks[0]['sha256'])
    build_pdf(manual,out/NAMES['manual']);build_pdf(quick,out/NAMES['quick'],quick=True)
    pdfchecks=[]
    for key in ('manual','quick'):
        reader=PdfReader(out/NAMES[key]);text='\n'.join(page.extract_text() or '' for page in reader.pages)
        (out/(key+'-extracted.txt')).write_text(text,encoding='utf-8')
        pdfchecks.append({'file':NAMES[key],'pages':len(reader.pages),'text_chars':len(text),'a4':all(all(abs(x-y)<1 for x,y in zip(sorted([float(p.mediabox.width),float(p.mediabox.height)]),sorted(A4))) for p in reader.pages),'bookmarks':len(reader.outline),'contains_replacement_character':'\ufffd' in text})
    record={'sources':checks,'pdfs':pdfchecks,'html_self_contained':True,'system_fonts_used_not_copied':['Microsoft YaHei','Microsoft YaHei Bold'],'outputs':{k:{'path':str(out/n),'sha256':hashlib.sha256((out/n).read_bytes()).hexdigest(),'bytes':(out/n).stat().st_size} for k,n in NAMES.items()}}
    (out/'build-validation.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(record,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
