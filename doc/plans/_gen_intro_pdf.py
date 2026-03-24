#!/usr/bin/env python3
"""Generate Q^AI project introduction PDF via weasyprint."""

import os, base64, weasyprint

# Encode demo screenshot as base64 for embedding
IMG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_demo_screenshot.png')
with open(IMG_PATH, 'rb') as f:
    IMG_B64 = base64.b64encode(f.read()).decode()

HTML_CONTENT = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<style>
  @page {{
    size: A4;
    margin: 16mm 20mm 10mm 20mm;
    @bottom-center {{
      content: counter(page) " / " counter(pages);
      font-size: 7.5pt;
      color: #999;
      font-family: "Noto Sans CJK SC", sans-serif;
    }}
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: "Noto Sans CJK SC", "Noto Sans SC", "Droid Sans Fallback", sans-serif;
    font-size: 9.5pt;
    line-height: 1.7;
    color: #2c2c2c;
  }}

  /* ---- Header ---- */
  .header {{
    display: flex;
    align-items: baseline;
    gap: 14px;
    margin-bottom: 2mm;
  }}
  .header h1 {{
    font-size: 28pt;
    font-weight: 700;
    color: #0f2b46;
    letter-spacing: 2px;
  }}
  .header .tagline {{
    font-size: 11pt;
    color: #3182ce;
    font-weight: 400;
  }}
  .header-line {{
    border: none;
    height: 3px;
    background: linear-gradient(90deg, #3182ce 0%, #63b3ed 100%);
    margin-bottom: 6mm;
  }}

  /* ---- Section headings ---- */
  h2 {{
    font-size: 12.5pt;
    font-weight: 700;
    color: #0f2b46;
    margin-top: 6mm;
    margin-bottom: 3mm;
    padding-left: 10px;
    border-left: 4px solid #3182ce;
  }}

  /* ---- Body ---- */
  p {{
    margin-bottom: 2mm;
    text-align: justify;
  }}

  /* ---- highlight box ---- */
  .highlight {{
    background: linear-gradient(135deg, #ebf5ff 0%, #f0f7ff 100%);
    border-left: 4px solid #3182ce;
    padding: 4mm 5mm;
    margin-bottom: 6mm;
    font-size: 10pt;
    border-radius: 0 4px 4px 0;
  }}

  /* ---- Two-column layout ---- */
  .columns {{
    display: flex;
    gap: 7mm;
  }}
  .col-left {{ flex: 1; }}
  .col-right {{ flex: 1; }}

  /* ---- Bullet list ---- */
  ul.items {{
    list-style: none;
    padding-left: 0;
    margin-bottom: 2.5mm;
  }}
  ul.items li {{
    margin-bottom: 1.8mm;
    padding-left: 5mm;
    text-indent: -5mm;
    line-height: 1.6;
  }}
  ul.items li::before {{
    content: "\\25B8\\00a0";
    color: #3182ce;
    font-size: 8pt;
  }}
  ul.items li b {{
    color: #0f2b46;
  }}

  /* ---- Tables ---- */
  table {{
    width: 100%;
    border-collapse: collapse;
    margin-bottom: 3mm;
    font-size: 9pt;
  }}
  th {{
    background: #0f2b46;
    color: #fff;
    font-weight: 600;
    text-align: center;
    padding: 5px 8px;
    font-size: 9pt;
  }}
  td {{
    padding: 4.5px 8px;
    border: 0.5px solid #d0dce8;
    vertical-align: middle;
  }}
  tr:nth-child(even) td {{ background: #f7fafc; }}

  /* ---- Demo image ---- */
  .demo-section {{
    margin-top: 6mm;
    margin-bottom: 4mm;
  }}
  .demo-section h2 {{
    margin-bottom: 4mm;
  }}
  .demo-img-wrap {{
    background: #0d1520;
    border-radius: 6px;
    padding: 4mm;
    text-align: center;
    box-shadow: 0 2px 8px rgba(0,0,0,0.15);
  }}
  .demo-img-wrap img {{
    width: 100%;
    border-radius: 3px;
  }}
  .demo-caption {{
    text-align: center;
    font-size: 8pt;
    color: #718096;
    margin-top: 2.5mm;
  }}

  /* ---- progress box ---- */
  .progress-box {{
    background: #f0fff4;
    border: 1px solid #c6f6d5;
    border-left: 4px solid #38a169;
    padding: 3.5mm 5mm;
    margin-bottom: 4mm;
    border-radius: 0 4px 4px 0;
    font-size: 9.5pt;
  }}
  .progress-box b {{ color: #276749; }}

  /* ---- Footer ---- */
  .footer-line {{
    border: none;
    height: 1px;
    background: #d0dce8;
    margin-top: 4mm;
    margin-bottom: 1.5mm;
  }}
  .footer-text {{
    text-align: center;
    font-size: 7.5pt;
    color: #a0aec0;
  }}
</style>
</head>
<body>

<!-- ==================== PAGE 1 ==================== -->

<div class="header">
  <h1>Q^AI</h1>
  <span class="tagline">AI 驱动的企业质量保障系统 &mdash; 汽车零部件行业</span>
</div>
<hr class="header-line">

<div class="highlight">
面向汽车零部件供应商，用 AI 将"客户询价 &rarr; 报价 &rarr; 量产交付"全流程的信息处理自动化。<br>
确保数据一致、来源可追溯、变更自动同步——从根源保障企业行为质量，守住利润。
</div>

<div class="columns">
<div class="col-left">

<h2>解决什么问题</h2>
<p>汽车零部件从询价到量产，涉及大量跨部门、跨文件的信息处理。行业普遍面临：</p>
<ul class="items">
  <li><b>信息散乱：</b>客户发来的文件多且复杂，人工整理耗时易错</li>
  <li><b>传递断裂：</b>部门之间靠人工传信息，前后不一致</li>
  <li><b>经验属人：</b>关键知识在个别人手里，人走经验散</li>
  <li><b>报价粗放：</b>成本算不清楚，中标后反而亏损</li>
</ul>

</div>
<div class="col-right">

<h2>我们怎么做</h2>
<p>基于大语言模型，深度结合行业知识，构建了一套自动化信息处理流水线：</p>
<ul class="items">
  <li><b>自动解析</b>客户文件，提取关键需求和技术要求</li>
  <li><b>自动推导</b>产品结构、风险分析、工艺方案、成本明细</li>
  <li><b>自动生成</b>符合客户格式的报价文件包</li>
  <li><b>变更联动</b>——任何数据更新，相关环节自动重算</li>
  <li><b>人机协作</b>——能确定的自动处理，不确定的标注提示</li>
</ul>

</div>
</div>

<!-- ===== Demo ===== -->
<div class="demo-section">
  <h2>系统演示 — 实际项目数据流</h2>
  <div class="demo-img-wrap">
    <img src="data:image/png;base64,{IMG_B64}" alt="Q^AI Dataflow Diagram">
  </div>
  <div class="demo-caption">从 RFQ 提取到最终报价的完整数据流</div>
</div>

<!-- ==================== PAGE 2 ==================== -->

<h2>项目进展</h2>
<div class="progress-box">
<b>POC 已完成</b>，系统可用性已通过实际项目验证。六家试点客户在谈，其中<b>三家有强烈付费意向，即将签约</b>。
</div>

<div class="columns">
<div class="col-left">

<h2>核心价值</h2>
<ul class="items">
  <li><b>报价精准：</b>成本逐项有依据，不再盲目报价</li>
  <li><b>效率翻倍：</b>报价周期缩短 70% 以上</li>
  <li><b>变更有据：</b>客户变更带来的成本影响清晰可查</li>
  <li><b>质量提升：</b>信息完整一致，交付物一次通过率高</li>
  <li><b>知识留存：</b>经验沉淀在系统中，不随人员流动丢失</li>
</ul>

</div>
<div class="col-right">

<h2>商业模式</h2>
<ul class="items">
  <li>一体机交付，本地化部署 + 培训 + 技术支持</li>
  <li>按用量收取算力使用费</li>
  <li>或为客户本地化部署大模型，数据完全不出厂</li>
</ul>

</div>
</div>

<h2>技术特点</h2>
<table>
  <tr><th style="width:160px">特性</th><th>说明</th></tr>
  <tr><td>多 Workflow、多 Agent 协同</td><td>多条工作流并行编排，多个 AI Agent 协同处理不同任务，具备适应泛化任务的能力，不局限于固定场景</td></tr>
  <tr><td>深度集成行业知识</td><td>内置行业标准、企业标准、质量管理体系方法论、失效模式，OEM 及零部件知识库，历史项目经验等，AI 推导有据可依</td></tr>
  <tr><td>自学习知识技能体系</td><td>项目经验持续沉淀，系统越用越聪明，推导越来越精准</td></tr>
  <tr><td>全程可追溯</td><td>每个数据标注来源和可信度，报价依据透明</td></tr>
  <tr><td>本地部署</td><td>数据不出客户网络，保障信息安全</td></tr>
</table>

<h2>目标市场</h2>
<p>国内汽车零部件一级供应商，涵盖管路、密封件、注塑件、冲压件等品类。适用于客户多、品类杂、流程复杂的中型及以上企业。</p>

<table>
  <tr><th>维度</th><th style="width:120px">估算</th></tr>
  <tr><td>国内 Tier 1 供应商总数</td><td style="text-align:center">约 3,000 家</td></tr>
  <tr><td>目标客群（中型及以上、多 OEM、流程复杂）</td><td style="text-align:center">约 800&ndash;1,000 家</td></tr>
  <tr><td>单客户年均产值（系统建设 + 年度服务）</td><td style="text-align:center">30&ndash;50 万元</td></tr>
  <tr><td>潜在市场规模（TAM）</td><td style="text-align:center">约 3&ndash;5 亿元/年</td></tr>
  <tr><td>近期可触达市场（SAM，首批品类覆盖）</td><td style="text-align:center">约 1 亿元/年</td></tr>
</table>

<h2>团队成员</h2>
<p>AI 专家（互联网大厂从业经验） &nbsp;/&nbsp; 零部件商质量管理高管 &nbsp;/&nbsp; 整车厂采购总监</p>

<hr class="footer-line">
<div class="footer-text">
Aaron &nbsp;|&nbsp; chuyinan20230327@gmail.com &nbsp;|&nbsp; +86 18101818763<br>
Q^AI &nbsp;|&nbsp; AI-Driven Quality Assurance for Automotive Tier 1 Suppliers &nbsp;|&nbsp; 2026
</div>

</body>
</html>
"""

def build_pdf(output_path):
    html = weasyprint.HTML(string=HTML_CONTENT)
    html.write_pdf(output_path)
    print(f"PDF generated: {output_path}")

if __name__ == '__main__':
    out_dir = os.path.dirname(os.path.abspath(__file__))
    output = os.path.join(out_dir, 'Q^AI-项目介绍.pdf')
    build_pdf(output)
