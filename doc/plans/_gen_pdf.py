#!/usr/bin/env python3
"""Generate professional PDF from markdown using weasyprint."""
import sys
import re
from pathlib import Path
from weasyprint import HTML

CSS = """
@page {
    size: A4;
    margin: 3cm 2.5cm 2.5cm 2.5cm;
    @bottom-right {
        content: counter(page);
        font-size: 8pt;
        color: #999;
        font-family: "Noto Sans CJK SC", sans-serif;
    }
    @top-left {
        content: "";
        border-bottom: 0.5pt solid #ddd;
    }
}

body {
    font-family: "Noto Sans CJK SC", "Noto Sans", "Helvetica Neue", sans-serif;
    font-size: 10.5pt;
    line-height: 1.8;
    color: #333;
    letter-spacing: 0.02em;
}

h1 {
    font-size: 18pt;
    font-weight: 300;
    color: #1a1a2e;
    border-bottom: none;
    margin-top: 50px;
    margin-bottom: 24px;
    padding-bottom: 12px;
    page-break-before: always;
    letter-spacing: 0.08em;
    border-left: 3px solid #0066cc;
    padding-left: 16px;
}

h1:first-of-type {
    page-break-before: avoid;
    margin-top: 0;
}

h2 {
    font-size: 13pt;
    font-weight: 600;
    color: #1a1a2e;
    margin-top: 28px;
    margin-bottom: 14px;
    border-left: none;
    padding-left: 0;
    letter-spacing: 0.04em;
}

h3 {
    font-size: 11pt;
    font-weight: 600;
    color: #444;
    margin-top: 20px;
    margin-bottom: 8px;
}

p {
    margin-bottom: 10px;
    text-align: justify;
}

ul, ol {
    margin-bottom: 12px;
    padding-left: 20px;
}

li {
    margin-bottom: 6px;
}

table {
    width: 100%;
    border-collapse: collapse;
    margin: 20px 0;
    font-size: 9.5pt;
}

thead th, th {
    background-color: #1a1a2e;
    color: #fff;
    font-weight: 600;
    padding: 10px 12px;
    border: none;
    text-align: left;
    letter-spacing: 0.03em;
    font-size: 9pt;
}

td {
    padding: 9px 12px;
    border-bottom: 1px solid #e8e8e8;
    vertical-align: top;
    color: #444;
}

th:first-child, td:first-child {
    white-space: nowrap;
    min-width: 5em;
}

tr:nth-child(even) td {
    background-color: #fafafa;
}

pre {
    background-color: #f5f5f5;
    border: none;
    border-left: 3px solid #ddd;
    padding: 14px 18px;
    font-family: "Noto Sans Mono CJK SC", "SF Mono", "Consolas", monospace;
    font-size: 8.5pt;
    line-height: 1.6;
    overflow-wrap: break-word;
    white-space: pre-wrap;
    margin: 16px 0;
    color: #555;
}

code {
    font-family: "Noto Sans Mono CJK SC", "SF Mono", "Consolas", monospace;
    font-size: 9pt;
    background-color: #f0f0f0;
    padding: 1px 5px;
    border-radius: 3px;
    color: #c7254e;
}

pre code {
    background: none;
    padding: 0;
    color: #555;
}

strong {
    color: #1a1a2e;
    font-weight: 600;
}

hr {
    border: none;
    border-top: 1px solid #eee;
    margin: 30px 0;
}

.toc {
    page-break-after: always;
}

.toc h1 {
    page-break-before: avoid;
    text-align: left;
    border-bottom: none;
    border-left: 3px solid #0066cc;
    padding-left: 16px;
    font-size: 18pt;
    font-weight: 300;
    letter-spacing: 0.08em;
    color: #1a1a2e;
    margin-bottom: 30px;
}

.toc ul {
    list-style: none;
    padding-left: 0;
    font-size: 11pt;
    line-height: 2.4;
}

.toc li {
    border-bottom: 1px solid #f0f0f0;
    padding: 2px 0;
    color: #333;
}

.toc li.h2-item {
    padding-left: 24px;
    font-size: 10pt;
    color: #666;
}

.cover {
    text-align: left;
    padding-top: 280px;
    padding-left: 20px;
    page-break-after: always;
}

.cover h1 {
    font-size: 32pt;
    font-weight: 300;
    border-bottom: none;
    border-left: 4px solid #0066cc;
    color: #1a1a2e;
    page-break-before: avoid;
    margin-bottom: 20px;
    text-align: left;
    padding-left: 20px;
    letter-spacing: 0.06em;
    line-height: 1.3;
}

.cover .subtitle {
    font-size: 14pt;
    font-weight: 300;
    color: #888;
    margin-bottom: 100px;
    text-align: left;
    padding-left: 24px;
    letter-spacing: 0.04em;
}

.cover .tagline {
    font-size: 11pt;
    font-weight: 400;
    color: #666;
    text-align: left;
    padding-left: 24px;
    letter-spacing: 0.04em;
    margin-bottom: 80px;
}

.cover .date {
    font-size: 10pt;
    font-weight: 400;
    color: #aaa;
    text-align: left;
    padding-left: 24px;
    letter-spacing: 0.06em;
}

.cover .confidential {
    font-size: 8pt;
    color: #bbb;
    text-align: left;
    padding-left: 24px;
    margin-top: 40px;
    text-transform: uppercase;
    letter-spacing: 0.15em;
}
"""


def md_to_html(md_text: str, title: str, subtitle: str = "") -> str:
    """Convert markdown to styled HTML."""
    lines = md_text.strip().split('\n')
    html_parts = []
    in_table = False
    in_code = False
    in_list = False
    table_rows = []
    code_lines = []
    list_items = []

    # Extract headings for TOC
    toc_items = []
    for line in lines:
        if line.startswith('# '):
            toc_items.append(('h1', line[2:].strip()))
        elif line.startswith('## '):
            toc_items.append(('h2', line[3:].strip()))

    def flush_list():
        nonlocal in_list, list_items
        if in_list and list_items:
            html_parts.append('<ul>')
            for item in list_items:
                html_parts.append(f'<li>{process_inline(item)}</li>')
            html_parts.append('</ul>')
            list_items = []
            in_list = False

    def flush_table():
        nonlocal in_table, table_rows
        if in_table and table_rows:
            html_parts.append('<table>')
            # First row as header
            header = table_rows[0]
            html_parts.append('<thead><tr>')
            for cell in header:
                html_parts.append(f'<th>{process_inline(cell.strip())}</th>')
            html_parts.append('</tr></thead>')
            # Data rows (skip separator row)
            html_parts.append('<tbody>')
            for row in table_rows[1:]:
                if all(c.strip().replace('-', '').replace('|', '') == '' for c in row):
                    continue
                html_parts.append('<tr>')
                for cell in row:
                    html_parts.append(f'<td>{process_inline(cell.strip())}</td>')
                html_parts.append('</tr>')
            html_parts.append('</tbody></table>')
            table_rows = []
            in_table = False

    def process_inline(text):
        # Bold
        text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
        # Inline code
        text = re.sub(r'`(.+?)`', r'<code>\1</code>', text)
        # Links (just show text)
        text = re.sub(r'\[(.+?)\]\(.+?\)', r'\1', text)
        return text

    # Build cover page
    html_parts.append(f'<div class="cover">')
    html_parts.append(f'<h1>{title}</h1>')
    if subtitle:
        html_parts.append(f'<p class="subtitle">{subtitle}</p>')
    html_parts.append(f'<p class="tagline">AI 驱动的企业质量保障系统</p>')
    html_parts.append(f'<p class="date">2026 年 3 月</p>')
    html_parts.append(f'<p class="confidential">Confidential</p>')
    html_parts.append(f'</div>')

    # Build TOC
    html_parts.append('<div class="toc">')
    html_parts.append('<h1>目 录</h1>')
    html_parts.append('<ul>')
    for level, heading in toc_items:
        cls = 'h2-item' if level == 'h2' else ''
        html_parts.append(f'<li class="{cls}">{heading}</li>')
    html_parts.append('</ul>')
    html_parts.append('</div>')

    for line in lines:
        # Code block
        if line.startswith('```'):
            if in_code:
                html_parts.append('\n'.join(code_lines))
                html_parts.append('</pre>')
                code_lines = []
                in_code = False
            else:
                flush_list()
                flush_table()
                in_code = True
            continue

        if in_code:
            # Escape HTML in code
            escaped = line.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            code_lines.append(escaped)
            continue

        # Table
        if '|' in line and line.strip().startswith('|'):
            flush_list()
            cells = [c for c in line.split('|')[1:-1]]
            if not in_table:
                in_table = True
            table_rows.append(cells)
            continue
        else:
            flush_table()

        # List
        if line.strip().startswith('- '):
            if not in_list:
                in_list = True
            list_items.append(line.strip()[2:])
            continue
        else:
            flush_list()

        # Headings
        if line.startswith('# '):
            html_parts.append(f'<h1>{process_inline(line[2:].strip())}</h1>')
        elif line.startswith('## '):
            html_parts.append(f'<h2>{process_inline(line[3:].strip())}</h2>')
        elif line.startswith('### '):
            html_parts.append(f'<h3>{process_inline(line[4:].strip())}</h3>')
        elif line.strip() == '---':
            continue  # Skip horizontal rules
        elif line.strip() == '':
            continue
        else:
            html_parts.append(f'<p>{process_inline(line)}</p>')

    flush_list()
    flush_table()

    full_html = f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<style>{CSS}</style>
</head>
<body>
{''.join(html_parts)}
</body>
</html>"""
    return full_html


def generate_pdf(md_path: str, pdf_path: str, title: str, subtitle: str = ""):
    md_text = Path(md_path).read_text(encoding='utf-8')
    html_content = md_to_html(md_text, title, subtitle)

    # Debug: save HTML
    html_path = pdf_path.replace('.pdf', '.html')
    Path(html_path).write_text(html_content, encoding='utf-8')

    HTML(string=html_content).write_pdf(pdf_path)
    size_kb = Path(pdf_path).stat().st_size // 1024
    print(f"✅ {pdf_path} ({size_kb} KB)")


if __name__ == '__main__':
    base = '/home/chu2026/Documents/APQPOS/doc/plans'

    generate_pdf(
        f'{base}/2026-03-18-technical-proposal.md',
        f'{base}/Q^AI-项目方案.pdf',
        'Q^AI',
        'Quality to the Power of AI'
    )

    generate_pdf(
        f'{base}/2026-03-18-technical-overview.md',
        f'{base}/Q^AI-技术概览.pdf',
        'Q^AI',
        'Quality to the Power of AI'
    )
