#!/usr/bin/env python3
"""
深度年报解析主程序

组织Graham/Buffett/Marks/Critic四位专家并行分析年报/半年报/季报/公告PDF，
输出结构化JSON报告。

用法:
  python3 parse_deep.py <股票代码> <输出目录> [选项]
  
选项:
  --type full       完整分析（年报+半年报+季报+公告）
  --type annual     仅年报分析（默认）
  --experts all     四专家并行（默认）
  --experts Graham,Buffett,Marks,Critic  指定专家
  --pdf-dir <路径>  PDF所在目录（默认同output_dir）
"""

import sys
import os
import json
import glob
import argparse
import pdfplumber
import re
from datetime import datetime

# ─────────────────────────────────────────
# 章节关键词映射
# ─────────────────────────────────────────

CHAPTER_KEYWORDS = {
    'financial_statements': [
        '会计政策和会计估计', '重要会计政策', '会计政策',
        '营业收入确认', '收入确认', '确认方法',
        '应收账款坏账', '预期信用损失', '坏账准备计提',
        '存货计价', '存货跌价准备', '成本与可变现净值',
        '固定资产折旧', '折旧年限', '残值率',
        '无形资产摊销', '开发支出资本化', '研发费用资本化',
        '关联方交易', '关联销售', '关联采购',
        '关键审计事项', '审计意见'
    ],
    'business_analysis': [
        '主要业务', '公司业务', '业务概要', '主营业务',
        '核心竞争力', '公司优势', '技术优势',
        '主要产品', '产品构成', '收入构成',
        '经营计划', '发展战略', '未来展望',
        '员工情况', '员工构成', '技术人员',
        '控股参股', '子公司情况', '少数股东权益'
    ],
    'risk_factors': [
        '风险因素', '重大风险提示', '风险提示',
        '或有事项', '担保情况', '诉讼仲裁',
        '经营风险', '行业风险', '政策风险',
        '应收账款质量', '账龄分析', '逾期情况',
        '带量采购', '集采', '医保谈判',
        '人才风险', '核心技术人员', '员工流失'
    ],
    'governance': [
        '前十大股东', '股东变化', '股东权益',
        '前五名客户', '客户集中度', '前五名供应商',
        '高级管理人员薪酬', '高管薪酬', '董事薪酬',
        '分红情况', '利润分配', '现金分红',
        '股份支付', '股权激励', '行权价格',
        '商誉', '减值测试',
        '在建工程', '工程进度',
        '募集资金使用', '募资用途', 'IPO募资'
    ]
}


# ─────────────────────────────────────────
# PDF解析核心（优化版）
# ─────────────────────────────────────────

def extract_pages(pdf_path, keywords, context_lines=8, max_results_per_kw=8):
    """
    按关键词在PDF中定位章节，返回上下文内容。
    优化：1)默认只扫描前120页 2)process_text=False提速 3)先整页预检再逐行提取
    """
    if not os.path.exists(pdf_path):
        return {}

    keywords_lower = {kw: kw.lower() for kw in keywords}
    results = {kw: [] for kw in keywords}

    try:
        with pdfplumber.open(pdf_path) as pdf:
            total_pages = len(pdf.pages)
            max_scan = min(120, total_pages)

            # 阶段1：快速构建relevant页面索引
            page_texts = {}
            for page_num in range(max_scan):
                page = pdf.pages[page_num]
                text = page.extract_text(process_text=False) or ''
                if not text:
                    continue
                text_lower = text.lower()
                if any(kw_lc in text_lower for kw_lc in keywords_lower.values()):
                    page_texts[page_num] = (text, text_lower)

            # 阶段2：逐行提取（只对relevant页面）
            for page_num, (text, text_lower) in page_texts.items():
                lines = text.split('\n')
                for kw, kw_lc in keywords_lower.items():
                    if len(results[kw]) >= max_results_per_kw:
                        continue
                    for i, line in enumerate(lines):
                        if kw in line or kw_lc in line.lower():
                            start = max(0, i - context_lines)
                            end = min(len(lines), i + context_lines + 1)
                            snippet = '\n'.join(lines[start:end])
                            results[kw].append({
                                'page': page_num + 1,
                                'line_num': i + 1,
                                'keyword': kw,
                                'context': snippet
                            })
    except Exception as e:
        print(f"  ⚠️ PDF解析警告: {e}")

    return {k: v for k, v in results.items() if v}


def extract_tables(pdf_path, keywords, max_rows=20):
    """提取含关键词的表格"""
    if not os.path.exists(pdf_path):
        return {}

    results = {}
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages[:60]:
                text = page.extract_text(process_text=False) or ''
                for kw in keywords:
                    if kw.lower() not in text.lower():
                        continue
                    tables = page.extract_tables() or []
                    for table in tables:
                        if not table:
                            continue
                        row_text = ' '.join([str(c) or '' for c in table[0]]) if table else ''
                        if kw in row_text:
                            key = f"{kw}_p{page.page_number}"
                            if key not in results:
                                results[key] = table[:max_rows]
    except Exception as e:
        print(f"  ⚠️ 表格提取警告: {e}")

    return results


# ─────────────────────────────────────────
# 四专家分析函数
# ─────────────────────────────────────────

def analyze_graham(texts, tables):
    """格雷厄姆风格：会计政策保守性 + 利润质量"""
    result = {
        'expert': 'Graham', 'score': 5, 'score_breakdown': {},
        'accounting_policy': {}, 'key_findings': [],
        'risk_signals': [], 'positive_signals': [], 'final_assessment': ''
    }

    # 1. 坏账计提
    ar = texts.get('应收账款坏账', []) + texts.get('预期信用损失', [])
    if ar:
        full = '\n'.join([t['context'] for t in ar])
        result['accounting_policy']['bad_debt'] = full[:300]
        rate = re.findall(r'1年以内[^\d]*(\d+(?:\.\d+)?)\s*%', full)
        if rate and float(rate[0]) >= 5:
            result['positive_signals'].append(f"1年以内坏账计提{rate[0]}%，符合格雷厄姆标准")
        elif rate:
            result['risk_signals'].append(f"1年以内坏账仅{rate[0]}%，偏激进")

    # 2. 研发资本化
    rd = texts.get('研发费用资本化', []) + texts.get('开发支出资本化', [])
    if rd:
        full = '\n'.join([t['context'] for t in rd])
        result['accounting_policy']['rd_capitalization'] = full[:300]
        if any(kw in full for kw in ['临床试验', '完成']):
            result['risk_signals'].append("研发资本化时点含'临床试验完成'字样，可能过早 ⚠️")
        elif '注册证' in full or '批准' in full:
            result['positive_signals'].append("资本化以注册批准为时点，较保守 ✅")

    # 3. 审计意见
    audit = texts.get('关键审计事项', []) + texts.get('审计意见', [])
    if audit:
        full = '\n'.join([t['context'] for t in audit])
        if '标准无保留' in full:
            result['positive_signals'].append("审计意见：标准无保留 ✅")
        if '收入确认' in full:
            result['risk_signals'].append("审计将'收入确认'列为关键审计事项 ⚠️")
        if '资本化' in full or '开发支出' in full:
            result['risk_signals'].append("审计将'研发支出资本化'列为关键审计事项 ⚠️")

    # 4. 关联交易
    rpt = texts.get('关联方交易', []) + texts.get('关联销售', []) + texts.get('关联采购', [])
    if rpt:
        amounts = []
        for t in rpt:
            amounts.extend(re.findall(r'([\d,]+(?:\.\d+)?)\s*(?:万|亿)?', t['context'])[:3])
        if amounts:
            result['accounting_policy']['related_party_amounts'] = amounts[:6]

    # 综合评分
    risk = len(result['risk_signals'])
    positive = len(result['positive_signals'])
    score = max(1, min(10, 5 + positive - risk))
    result['score'] = score
    result['final_assessment'] = f"Graham评分{score}/10。风险信号{risk}个，积极信号{positive}个。{'-'.join(result['risk_signals'][:2])}"

    return result


def analyze_buffett(texts, tables):
    """巴菲特风格：商业模式 + 护城河 + 管理层诚信"""
    result = {
        'expert': 'Buffett', 'score': 5, 'score_breakdown': {},
        'business_quality': {}, 'moat_analysis': {}, 'management_assessment': {},
        'key_findings': [], 'risk_signals': [], 'positive_signals': [], 'final_assessment': ''
    }

    # 业务描述
    biz = texts.get('主要业务', []) + texts.get('公司业务', []) + texts.get('主营业务', [])
    if biz:
        full = '\n'.join([t['context'] for t in biz[:2]])
        result['business_quality']['description'] = full[:400]
        result['business_quality']['complexity'] = '复杂' if any(
            kw in full for kw in ['高壁垒', '技术创新', '专利', '三类', '注册证']
        ) else '一般'

    # 护城河
    moat = texts.get('核心竞争力', []) + texts.get('公司优势', []) + texts.get('技术优势', [])
    if moat:
        full = '\n'.join([t['context'] for t in moat[:2]])
        result['moat_analysis']['description'] = full[:300]
        types = []
        if '专利' in full: types.append('无形资产')
        if '临床' in full or '手术' in full: types.append('转换成本')
        if '注册证' in full: types.append('行政许可壁垒')
        result['moat_analysis']['types'] = types if types else ['难以判断']

    # 管理层语调
    strat = texts.get('经营计划', []) + texts.get('发展战略', []) + texts.get('未来展望', [])
    if strat:
        full = '\n'.join([t['context'] for t in strat[:2]])
        result['management_assessment']['strategy'] = full[:300]
        opt = sum(1 for w in ['领先', '优势', '突破', '增长', '加速'] if w in full)
        con = sum(1 for w in ['面临', '挑战', '风险', '不确定', '竞争加剧'] if w in full)
        result['management_assessment']['tone'] = '偏乐观' if opt > con * 2 else ('偏谨慎' if con > opt else '中性')

    # 子公司亏损
    sub = texts.get('控股参股', []) + texts.get('子公司情况', [])
    for t in sub:
        if any(kw in t['context'] for kw in ['亏损', '未盈利', '持续亏损']):
            result['risk_signals'].append("存在亏损子公司 ⚠️")
            break

    score = max(1, min(10, 5 - len(result['risk_signals']) + len(result.get('positive_signals', []))))
    result['score'] = score
    result['final_assessment'] = f"Buffett评分{score}/10。护城河：{result['moat_analysis'].get('types', ['未知'])}，语调：{result['management_assessment'].get('tone', '未知')}"

    return result


def analyze_marks(texts, tables):
    """霍华德·马克斯风格：风险 + 第二层思维 + 周期"""
    result = {
        'expert': 'Marks', 'score': 5, 'score_breakdown': {},
        'disclosed_risks': {}, 'hidden_risks': [],
        'second_level_thinking': {}, 'cycle_position': 'unknown',
        'key_findings': [], 'risk_signals': [], 'final_assessment': ''
    }

    # 已披露风险
    risk = texts.get('风险因素', []) + texts.get('重大风险提示', [])
    if risk:
        categorized = {'行业风险': [], '经营风险': [], '政策风险': [], '财务风险': [], '法律风险': []}
        full = '\n'.join([t['context'] for t in risk[:4]])
        cats = {
            '行业风险': ['竞争加剧', '外资品牌', '市场份额', '技术迭代'],
            '经营风险': ['人才流失', '核心人员', '经销商', '产品质量'],
            '政策风险': ['集采', '带量采购', '医保谈判', '审批延迟'],
            '财务风险': ['应收账款', '坏账', '存货积压', '汇率'],
            '法律风险': ['诉讼', '仲裁', '行政处罚']
        }
        for cat, kw_list in cats.items():
            for kw in kw_list:
                if kw in full:
                    for line in full.split('\n'):
                        if kw in line and 10 < len(line) < 200:
                            categorized[cat].append(line.strip()[:120])
                            break
        result['disclosed_risks'] = {k: v[:2] for k, v in categorized.items() if v}

    # 政策风险
    pol = texts.get('带量采购', []) + texts.get('集采', [])
    for t in pol:
        if '首次' in t['context'] or '纳入' in t['context']:
            result['hidden_risks'].append("集采首次纳入该公司产品，降价风险尚未充分定价 ⚠️")

    # 募资滞后
    fund = texts.get('募集资金使用', []) + texts.get('IPO募资', [])
    for t in fund:
        for p in re.findall(r'(\d+(?:\.\d+)?)\s*%', t['context']):
            if float(p) < 30:
                result['hidden_risks'].append(f"募投项目严重滞后：进度仅{p}% ⚠️")
                break

    # 人才风险
    talent = texts.get('人才风险', []) + texts.get('员工流失', [])
    for t in talent:
        if any(kw in t['context'] for kw in ['减少', '离职', '流失']):
            result['hidden_risks'].append("员工/技术人员流失风险 ⚠️")

    disclosed = sum(len(v) for v in result['disclosed_risks'].values())
    score = max(1, min(10, 7 - len(result['hidden_risks']) * 1.5 + disclosed * 0.3))
    result['score'] = round(score, 1)
    result['final_assessment'] = f"Marks评分{result['score']}/10。已披露{disclosed}条，隐藏{len(result['hidden_risks'])}条。"

    return result


def analyze_critic(texts, tables, other_results=None):
    """批评者风格：质疑 + 治理 + 股东 + 募资"""
    result = {
        'expert': 'Critic', 'score': 5,
        'supplementary_data': {}, 'ignored_issues': [],
        'core_questions': [], 'final_recommendation': '观望',
        'key_findings': [], 'risk_signals': [], 'final_assessment': ''
    }

    # 股东结构
    gov = texts.get('前十大股东', []) + texts.get('股东变化', [])
    for t in gov:
        result['supplementary_data']['shareholder_info'] = t['context'][:300]
        if any(kw in t['context'] for kw in ['解禁', '锁定期', '锁定']):
            for m in re.findall(r'(?:解禁|锁定期).{0,100}', t['context'])[:2]:
                result['ignored_issues'].append(f"解禁风险：{m}")
        ratios = re.findall(r'(\d+(?:\.\d+)?)\s*%', t['context'])
        if ratios:
            result['supplementary_data']['top_shareholders'] = f"前股东占比：{ratios[:5]}"
        break

    # 客户/供应商集中度
    cust = texts.get('前五名客户', []) + texts.get('客户集中度', [])
    for t in cust:
        ratios = re.findall(r'(\d+(?:\.\d+)?)\s*%', t['context'])
        if ratios and float(ratios[0]) > 40:
            result['ignored_issues'].append(f"客户集中度过高：{ratios[0]}% (>40%) ⚠️")
        result['supplementary_data']['customer_concentration'] = f"前五客户：{ratios[0] if ratios else '?'}%"
        break

    sup = texts.get('前五名供应商', [])
    for t in sup:
        ratios = re.findall(r'(\d+(?:\.\d+)?)\s*%', t['context'])
        if ratios:
            result['supplementary_data']['supplier_concentration'] = f"前五供应商：{ratios[0]}%"
        break

    # 高管薪酬
    comp = texts.get('高管薪酬', []) + texts.get('股权激励', [])
    for t in comp:
        amounts = re.findall(r'([\d,]+)\s*万', t['context'])
        if amounts:
            result['supplementary_data']['executive_comp'] = f"高管薪酬：{amounts[0]}万"
        prices = re.findall(r'(\d+(?:\.\d+)?)\s*元', t['context'])
        if prices:
            result['supplementary_data']['option_prices'] = [f"{p}元" for p in prices[:5]]
        break

    # 分红
    div = texts.get('分红情况', []) + texts.get('现金分红', [])
    for t in div:
        if '不分' in t['context']:
            result['ignored_issues'].append("存在未分配利润但未分红 ⚠️")
        break

    # 募资使用
    fund = texts.get('募集资金使用', []) + texts.get('IPO募资', [])
    for t in fund:
        result['supplementary_data']['fund_usage'] = t['context'][:300]
        for p in re.findall(r'(\d+(?:\.\d+)?)\s*%', t['context']):
            if float(p) < 30:
                result['ignored_issues'].append(f"募投项目严重滞后：进度仅{p}% ⚠️")
                break

    result['core_questions'] = result['ignored_issues'][:5]

    # 综合建议
    all_scores = [result['score']]
    if other_results:
        all_scores.extend([r['score'] for r in other_results if r and 'score' in r])
    avg = sum(all_scores) / len(all_scores)

    if avg < 4: rec, score = '强烈回避', 3
    elif avg < 5.5: rec, score = '回避', 4
    elif avg < 6.5: rec, score = '观望', 5
    elif avg < 7.5: rec, score = '关注', 6
    else: rec, score = '买入', 7

    result['final_recommendation'] = rec
    result['score'] = score
    result['final_assessment'] = f"Critic评分{score}/10。建议：{rec}。核心：{result['ignored_issues'][0][:80] if result['ignored_issues'] else '无'}"

    return result


# ─────────────────────────────────────────
# 预提取 + 专家调度
# ─────────────────────────────────────────

def pre_extract_pdf(pdf_path):
    """一次性提取PDF所有章节文本，供所有专家共享"""
    print("  📖 预扫描PDF（一次性提取）...")
    all_keywords = []
    for kws in CHAPTER_KEYWORDS.values():
        all_keywords.extend(kws)
    texts = extract_pages(pdf_path, all_keywords)
    total_hits = sum(len(v) for v in texts.values())
    print(f"  ✅ 提取完成：{total_hits} 个关键词命中，{len(texts)} 个章节有内容")
    return texts


def run_experts_with_texts(experts, stock_code, output_dir, all_texts, other_results=None):
    """运行专家分析（使用预提取文本）"""
    results = []
    other = other_results or []

    for expert in experts:
        print(f"  🎯 {expert}...", end='', flush=True)
        if expert == 'Graham':
            r = analyze_graham(all_texts, {})
        elif expert == 'Buffett':
            r = analyze_buffett(all_texts, {})
        elif expert == 'Marks':
            r = analyze_marks(all_texts, {})
        elif expert == 'Critic':
            r = analyze_critic(all_texts, {}, other)
        else:
            continue

        out_file = os.path.join(output_dir, f"{stock_code}_{expert}_result.json")
        with open(out_file, 'w', encoding='utf-8') as f:
            json.dump(r, f, ensure_ascii=False, indent=2)
        print(f" ✅ {r.get('score', '?')}/10")
        results.append(r)
        other.append(r)

    return results


# ─────────────────────────────────────────
# 汇总
# ─────────────────────────────────────────

def synthesize(stock_code, results, output_dir):
    """汇总四专家结果"""
    scores = [r['score'] for r in results if r and 'score' in r]
    avg = sum(scores) / len(scores) if scores else 5

    recommendations = list({r.get('final_recommendation', '观望') for r in results if r})

    synthesis = {
        'meta': {
            'stock_code': stock_code,
            'analysis_date': datetime.now().strftime('%Y-%m-%d'),
            'data_sources': ['annual_pdf'],
            'experts': [r['expert'] for r in results if r]
        },
        'individual_results': {
            r['expert']: {
                'score': r.get('score'),
                'recommendation': r.get('final_recommendation', ''),
                'key_risks': (r.get('risk_signals', []) + r.get('hidden_risks', []))[:3],
                'key_positive': r.get('positive_signals', [])[:3],
                'assessment': r.get('final_assessment', '')
            } for r in results if r
        },
        'synthesis': {
            'composite_score': round(avg, 1),
            'score_range': f"{min(scores)}-{max(scores)}" if scores else "?",
            'recommendations': recommendations,
            'consensus': f"评分{avg:.1f}，建议{'/'.join(recommendations)}"
        }
    }

    if avg < 4:
        synthesis['final_recommendation'] = '强烈回避'
        synthesis['investment_thesis'] = f"综合评分{avg:.1f}/10，四专家均提示显著风险，当前估值安全边际严重不足。"
    elif avg < 5.5:
        synthesis['final_recommendation'] = '回避'
        synthesis['investment_thesis'] = f"综合评分{avg:.1f}/10，存在多个风险点，建议等待更安全边际。"
    elif avg < 6.5:
        synthesis['final_recommendation'] = '观望'
        synthesis['investment_thesis'] = f"综合评分{avg:.1f}/10，基本面与估值基本匹配，建议等待催化剂。"
    elif avg < 7.5:
        synthesis['final_recommendation'] = '关注'
        synthesis['investment_thesis'] = f"综合评分{avg:.1f}/10，基本面扎实，估值合理偏低，值得关注。"
    else:
        synthesis['final_recommendation'] = '买入'
        synthesis['investment_thesis'] = f"综合评分{avg:.1f}/10，多位专家认可投资价值，具备安全边际。"

    out_file = os.path.join(output_dir, f"{stock_code}_deep_analysis_report.json")
    with open(out_file, 'w', encoding='utf-8') as f:
        json.dump(synthesis, f, ensure_ascii=False, indent=2)
    print(f"\n  ✅ 综合报告 → {out_file}")

    return synthesis


# ─────────────────────────────────────────
# 主入口
# ─────────────────────────────────────────

def find_latest_pdf(directory, patterns):
    """查找最新匹配的PDF"""
    found = {}
    for pattern in patterns:
        files = glob.glob(os.path.join(directory, pattern))
        if files:
            found[pattern] = max(files, key=os.path.getmtime)
    return found


def main(stock_code, output_dir, experts=None, pdf_dir=None):
    os.makedirs(output_dir, exist_ok=True)
    pdf_dir = pdf_dir or output_dir

    if experts is None:
        experts = ['Graham', 'Buffett', 'Marks', 'Critic']

    patterns = [
        '*2025年年度报告*.pdf', '*2024年年度报告*.pdf',
        '*年度报告*.pdf', '*年报*.pdf'
    ]

    found = find_latest_pdf(pdf_dir, patterns)
    if not found:
        print(f"❌ 在 {pdf_dir} 中未找到年报PDF")
        return

    pdf_path = list(found.values())[0]
    size_mb = os.path.getsize(pdf_path) / 1024 / 1024
    print(f"\n📄 使用: {os.path.basename(pdf_path)} ({size_mb:.1f} MB)")

    # 预提取
    all_texts = pre_extract_pdf(pdf_path)

    # 四专家分析
    print(f"\n{'='*50}")
    print(f"🎯 深度年报解析 — {stock_code}")
    print(f"{'='*50}")

    results = run_experts_with_texts(experts, stock_code, output_dir, all_texts)

    if results:
        s = synthesize(stock_code, results, output_dir)
        print(f"\n{'='*50}")
        print(f"📊 四专家汇总")
        print(f"{'='*50}")
        for r in results:
            print(f"  {r['expert']:10s}: {r.get('score', '?'):4.1f}/10  {r.get('final_assessment', '')[:60]}")
        print(f"{'='*50}")
        print(f"  综合评分: {s['synthesis']['composite_score']}/10")
        print(f"  投资建议: {s['final_recommendation']}")
        print(f"  核心逻辑: {s['investment_thesis'][:100]}")
        print(f"{'='*50}")
        print(f"\n✅ 完成！结果保存在: {output_dir}/")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='深度年报解析 — 四专家框架')
    parser.add_argument('stock_code', help='股票代码')
    parser.add_argument('output_dir', help='输出目录')
    parser.add_argument('--experts', default='Graham,Buffett,Marks,Critic',
                        help='启用的专家（逗号分隔）')
    parser.add_argument('--pdf-dir', help='PDF所在目录（默认同output_dir）')
    args = parser.parse_args()

    experts = [e.strip() for e in args.experts.split(',')]
    main(args.stock_code, args.output_dir, experts, args.pdf_dir)
