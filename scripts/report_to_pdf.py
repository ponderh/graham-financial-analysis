#!/usr/bin/env python3
"""
分析报告转PDF模块
将markdown分析报告转换为精美PDF

用法:
  python3 report_to_pdf.py <报告.md> [输出.pdf]
  python3 report_to_pdf.py FINAL_ANALYSIS_REPORT.md output.pdf
"""

import sys
import os
import re
import string as str_module


HTML_CSS = """
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  font-family: 'Noto Sans SC', 'Source Han Sans SC', 'WenQuanYi Micro Hei',
               'Microsoft YaHei', 'SimHei', sans-serif;
  font-size: 10pt;
  line-height: 1.7;
  color: #222;
  background: white;
}
@page {
  size: A4;
  margin: 18mm 20mm 18mm 22mm;
}
@page :first { margin: 15mm; }
h1 {
  font-size: 16pt;
  font-weight: 700;
  color: #1a1a2e;
  border-bottom: 2px solid #1a1a2e;
  padding-bottom: 5px;
  margin: 14px 0 10px 0;
  page-break-after: avoid;
}
h2 {
  font-size: 12pt;
  font-weight: 700;
  color: white;
  background: #1a1a2e;
  padding: 5px 12px;
  margin: 16px 0 8px 0;
  page-break-after: avoid;
}
h3 {
  font-size: 10.5pt;
  font-weight: 600;
  color: #333;
  border-bottom: 1px solid #ddd;
  padding-bottom: 2px;
  margin: 10px 0 5px 0;
  page-break-after: avoid;
}
p { margin: 4px 0; text-align: justify; }
table {
  width: 100%;
  border-collapse: collapse;
  margin: 6px 0;
  font-size: 8.5pt;
  page-break-inside: avoid;
}
th {
  background: #1a1a2e;
  color: white;
  padding: 5px 7px;
  text-align: center;
  font-weight: 600;
  border: 1px solid #1a1a2e;
}
td {
  padding: 4px 7px;
  border: 1px solid #ccc;
  vertical-align: middle;
}
tr:nth-child(even) { background: #f5f6f7; }
tr:nth-child(odd) { background: white; }
.good { color: #16a34a; font-weight: 600; }
.bad { color: #dc2626; font-weight: 600; }
.warn { color: #d97706; font-weight: 600; }
.box-warn {
  background: #fef9c3;
  border-left: 3px solid #ca8a04;
  padding: 6px 10px;
  margin: 6px 0;
  font-size: 9pt;
}
.box-bad {
  background: #fee2e2;
  border-left: 3px solid #dc2626;
  padding: 6px 10px;
  margin: 6px 0;
  font-size: 9pt;
}
.box-good {
  background: #dcfce7;
  border-left: 3px solid #16a34a;
  padding: 6px 10px;
  margin: 6px 0;
  font-size: 9pt;
}
ul, ol { margin: 3px 0 3px 18px; font-size: 9pt; }
li { margin: 2px 0; }
code {
  font-family: monospace;
  background: #f1f5f9;
  padding: 1px 4px;
  border-radius: 2px;
  font-size: 8pt;
}
hr { border: none; border-top: 1px solid #e5e7eb; margin: 10px 0; }
.footer {
  margin-top: 25px;
  padding-top: 8px;
  border-top: 1px solid #ddd;
  font-size: 8pt;
  color: #888;
  text-align: center;
}
"""


def md_to_html(text):
    """简化Markdown转HTML"""
    lines = text.split('\n')
    html = []
    in_table = False
    in_list = False
    i = 0
    
    while i < len(lines):
        line = lines[i]
        s = line.strip()
        
        if not s:
            if in_table:
                html.append('</tbody></table>')
                in_table = False
            if in_list:
                html.append('</ul>')
                in_list = False
            html.append('')
            i += 1
            continue
        
        # 标题
        if s.startswith('# '):
            if in_table:
                html.append('</tbody></table>')
                in_table = False
            if in_list:
                html.append('</ul>')
                in_list = False
            title = re.sub(r'\(([^)]+)\)$', '', s[2:]).strip()
            html.append(f'<h1>{title}</h1>')
            i += 1
            continue
        
        if s.startswith('## '):
            if in_table:
                html.append('</tbody></table>')
                in_table = False
            if in_list:
                html.append('</ul>')
                in_list = False
            html.append(f'<h2>{s[3:]}</h2>')
            i += 1
            continue
        
        if s.startswith('### '):
            if in_table:
                html.append('</tbody></table>')
                in_table = False
            if in_list:
                html.append('</ul>')
                in_list = False
            html.append(f'<h3>{s[4:]}</h3>')
            i += 1
            continue
        
        if s.startswith('---'):
            html.append('<hr>')
            i += 1
            continue
        
        # 表格
        if s.startswith('|') and s.endswith('|'):
            if not in_table:
                html.append('<table><tbody>')
                in_table = True
            
            cells = [c.strip() for c in s.split('|')[1:-1]]
            if all(re.match(r'^[-:]+$', c.replace(' ', '')) for c in cells if c):
                i += 1
                continue
            
            is_header = any(kw in ' '.join(c.lower() for c in cells)
                          for kw in ['指标', '维度', '模块', '年份', '方法', '检查', '评估', '类型', '项目', '名称', '对比', '评估', '报告'])
            
            if is_header:
                html.append('<thead>')
                html.append('<tr>')
                for cell in cells:
                    html.append(f'<th>{cell}</th>')
                html.append('</tr>')
                html.append('</thead>')
                html.append('<tbody>')
            else:
                html.append('<tr>')
                for cell in cells:
                    # 评分着色
                    if re.match(r'^\d+/\d+$', cell):
                        try:
                            score = int(cell.split('/')[0])
                            total = int(cell.split('/')[1])
                            ratio = score / total
                            cls = 'good' if ratio >= 0.7 else ('warn' if ratio >= 0.4 else 'bad')
                            cell = f'<span class="{cls}">{cell}</span>'
                        except (ValueError, IndexError):
                            pass
                    html.append(f'<td>{cell}</td>')
                html.append('</tr>')
            i += 1
            continue
        
        # 列表
        if s.startswith('- ') or s.startswith('* '):
            if not in_list:
                html.append('<ul>')
                in_list = True
            content = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', s[2:])
            html.append(f'<li>{content}</li>')
            i += 1
            continue
        
        # 其他段落
        if in_table:
            html.append('</tbody></table>')
            in_table = False
        if in_list:
            html.append('</ul>')
            in_list = False
        
        # 特殊框
        if '🔴' in s or '❌' in s:
            text = re.sub(r'[🔴❌]\s*', '', s)
            text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
            html.append(f'<div class="box-bad">{text}</div>')
        elif '⚠️' in s or '⚠️' in s:
            text = re.sub(r'[⚠️⚠]\s*', '', s)
            text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
            html.append(f'<div class="box-warn">{text}</div>')
        elif '✅' in s:
            text = re.sub(r'[✅]\s*', '', s)
            text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
            html.append(f'<div class="box-good">{text}</div>')
        else:
            text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', s)
            text = re.sub(r'`(.+?)`', r'<code>\1</code>', text)
            text = re.sub(r'\[(.+?)\]\(.+?\)', r'\1', text)
            html.append(f'<p>{text}</p>')
        
        i += 1
    
    if in_table:
        html.append('</tbody></table>')
    if in_list:
        html.append('</ul>')
    
    return '\n'.join(html)


def markdown_to_pdf(md_path, pdf_path=None):
    """将Markdown转换为PDF"""
    if not os.path.exists(md_path):
        print(f"❌ 文件不存在: {md_path}")
        return False
    
    with open(md_path, 'r', encoding='utf-8') as f:
        md_content = f.read()
    
    # 提取元信息
    ticker = ''
    report_date = ''
    for line in md_content.split('\n')[:15]:
        m = re.search(r'\((\d{6})\)', line)
        if m:
            ticker = m.group(1)
        m = re.search(r'(\d{4}-\d{2}-\d{2})', line)
        if m:
            report_date = m.group(1)
    
    if not report_date:
        from datetime import date
        report_date = date.today().isoformat()
    
    html_content = md_to_html(md_content)
    
    # 封面
    title_match = re.search(r'^#\s+(.+?)\s*\(', md_content, re.MULTILINE)
    if not title_match:
        title_match = re.search(r'^#\s+(.+)', md_content, re.MULTILINE)
    title = title_match.group(1).strip() if title_match else '股票分析报告'
    
    cover = f"""
    <div style="page-break-after: always; text-align: center; 
                background: linear-gradient(135deg, #1a1a2e, #16213e);
                color: white; padding: 60px 40px; min-height: 240mm;">
      <h1 style="color: white; border: none; font-size: 22pt; margin-bottom: 8px;">{title}</h1>
      <div style="font-size: 14pt; color: #94a3b8; margin: 20px 0;">{ticker}</div>
      <div style="font-size: 10pt; color: #64748b; margin-top: 40px;">分析日期: {report_date}</div>
      <div style="font-size: 9pt; color: #475569; margin-top: 10px;">格雷厄姆多专家协作框架 v2</div>
    </div>
    """
    
    footer = f"""
    <div class="footer">
      <p>本报告由格雷厄姆多专家协作框架生成 | 数据来源: akshare + 交易所年报PDF | 分析日期: {report_date}</p>
      <p>报告仅供参考，不构成投资建议</p>
    </div>
    """
    
    full_html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<style>{HTML_CSS}</style>
</head>
<body>
{cover}
{html_content}
{footer}
</body>
</html>"""
    
    if not pdf_path:
        base = os.path.splitext(md_path)[0]
        pdf_path = base + '.pdf'
    
    try:
        from weasyprint import HTML as WeasyHTML
        print(f"正在生成PDF: {pdf_path}")
        WeasyHTML(string=full_html, base_url=os.path.dirname(md_path) or '.').write_pdf(pdf_path)
        size = os.path.getsize(pdf_path)
        print(f"✅ PDF生成成功: {pdf_path} ({size//1024}KB)")
        return True
    except ImportError:
        print("❌ weasyprint未安装: pip install weasyprint")
        return False
    except Exception as e:
        print(f"❌ PDF生成失败: {e}")
        return False


def main():
    if len(sys.argv) < 2:
        print("用法: python3 report_to_pdf.py <报告.md> [输出.pdf]")
        sys.exit(1)
    
    md_path = sys.argv[1]
    pdf_path = sys.argv[2] if len(sys.argv) > 2 else None
    
    success = markdown_to_pdf(md_path, pdf_path)
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
