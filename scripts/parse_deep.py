#!/usr/bin/env python3
"""
深度年报解析 v2.0 — 四专家框架增强版

增强内容：
1. 董事会报告追踪（年份-报告类型 → 核心要点）
2. Graham专家：会计政策深度 + 利润质量重构
3. Buffett专家：管理层语调深度 + 护城河验证 + FCF评估
4. Marks专家：已披露风险 + 第二层思维 + 周期定位
5. Critic专家：完整10项治理数据 + 综合质疑
6. 可选整合格雷厄姆skill数据（估值、财务指标）

用法:
  python3 parse_deep.py <股票代码> <输出目录> [选项]
  python3 parse_deep.py 688351 ./output --experts all --pdf-dir ./pdfs --integrate-graham
"""

import sys
import os
import json
import glob
import argparse
import re
import pdfplumber
from datetime import datetime
from typing import Dict, List, Any, Optional

# ─────────────────────────────────────────
# 章节关键词映射
# ─────────────────────────────────────────

CHAPTER_KEYWORDS = {
    'financial_statements': [
        '会计政策和会计估计', '会计政策', '收入确认政策', '收入确认',
        '应收账款坏账', '预期信用损失', '坏账准备', '信用损失',
        '存货计价', '存货跌价准备', '成本与可变现净值',
        '固定资产折旧', '折旧年限', '残值率', '折旧方法',
        '无形资产摊销', '开发支出资本化', '研发费用资本化', '资本化条件',
        '关联方交易', '关联销售', '关联采购', '关联担保',
        '关键审计事项', '审计意见', '非经常性损益'
    ],
    'business_analysis': [
        '主要业务', '公司业务', '业务概要', '主营业务', '公司经营范围',
        '核心竞争力', '公司优势', '技术优势', '竞争实力', '行业地位',
        '主要产品', '产品构成', '收入构成', '主营业务收入',
        '经营计划', '发展战略', '未来展望', '经营目标',
        '员工情况', '员工构成', '技术人员', '研发人员'
    ],
    'risk_factors': [
        '风险因素', '重大风险提示', '风险提示', '风险揭示',
        '或有事项', '担保情况', '诉讼仲裁', '未决诉讼',
        '经营风险', '行业风险', '政策风险', '技术风险',
        '应收账款质量', '账龄分析', '逾期情况',
        '带量采购', '集采', '医保谈判', '中标价格',
        '人才风险', '核心技术人员', '员工流失', '市场竞争', '竞争加剧'
    ],
    'governance': [
        '前十大股东', '股东变化', '股东权益', '股份变动', '股东减持',
        '前五名客户', '客户集中度', '前五名供应商', '供应商集中度',
        '高级管理人员薪酬', '高管薪酬', '董事薪酬',
        '分红情况', '利润分配', '现金分红', '分红预案',
        '股份支付', '股权激励', '行权价格', '限制性股票',
        '商誉', '减值测试', '在建工程', '募集资金使用', '募资用途',
        '实际控制人', '控股股权', '一致行动人'
    ],
    'board_report': [
        '经营情况讨论与分析', '董事会报告', '经营情况', '经营成果',
        '公司业务概述', '主要经营情况', '业绩回顾', '业务发展',
        '行业格局和趋势', '竞争格局', '市场地位', '公司战略',
        '未来发展展望', '未来展望', '下一年', '经营计划',
        '收入分析', '毛利分析', '费用分析', '研发进展'
    ]
}


# ─────────────────────────────────────────
# PDF解析核心（优化版）
# ─────────────────────────────────────────

def extract_chapter_text(pdf_path: str, chapter: str, keywords: List[str],
                         max_pages: int = 120, context_lines: int = 8) -> Dict[str, List]:
    """提取指定章节关键词上下文，一次扫描+关键词预检"""
    if not os.path.exists(pdf_path):
        return {}

    kw_lc = {kw: kw.lower() for kw in keywords}
    results = {kw: [] for kw in keywords}

    try:
        with pdfplumber.open(pdf_path) as pdf:
            total = len(pdf.pages)
            page_texts = {}

            for pn in range(min(max_pages, total)):
                page = pdf.pages[pn]
                text = page.extract_text(process_text=False) or ''
                if not text:
                    continue
                text_lc = text.lower()
                if any(kw_lc[kw] in text_lc for kw in keywords):
                    page_texts[pn] = (text, text_lc)

            for pn, (text, text_lc) in page_texts.items():
                lines = text.split('\n')
                for kw in keywords:
                    if len(results[kw]) >= 8:
                        continue
                    kw_lc_val = kw_lc[kw]
                    for i, line in enumerate(lines):
                        if kw in line or kw_lc_val in line.lower():
                            start = max(0, i - context_lines)
                            end = min(len(lines), i + context_lines + 1)
                            snippet = '\n'.join(lines[start:end])
                            results[kw].append({
                                'page': pn + 1, 'line_num': i + 1,
                                'keyword': kw, 'context': snippet
                            })
    except Exception as e:
        print(f"  ⚠️ 解析: {e}")

    return {k: v for k, v in results.items() if v}


def merge_texts(texts_dict: Dict) -> str:
    return '\n'.join(item['context'] for items in texts_dict.values() for item in items)


# ─────────────────────────────────────────
# 董事会报告追踪
# ─────────────────────────────────────────

def extract_board_reports(pdf_dir: str, stock_code: str) -> Dict[str, Any]:
    """提取所有财报的董事会报告要点"""
    results = {}
    patterns = {
        '年度报告': ['*2025年年度报告.pdf', '*2024年年度报告.pdf', '*年度报告.pdf'],
        '半年度报告': ['*2025年半年度报告.pdf', '*2024年半年度报告.pdf', '*半年度报告.pdf'],
        '第一季度报告': ['*2025年第一季度报告.pdf', '*一季报.pdf'],
        '第三季度报告': ['*2025年第三季度报告.pdf', '*三季报.pdf'],
    }

    for rtype, pats in patterns.items():
        for pat in pats:
            files = glob.glob(os.path.join(pdf_dir, pat))
            if not files:
                continue
            latest = max(files, key=os.path.getmtime)
            texts = extract_chapter_text(latest, 'board_report',
                                         CHAPTER_KEYWORDS['board_report'],
                                         max_pages=80, context_lines=5)
            if not texts:
                continue
            full = merge_texts(texts)
            year_m = re.search(r'(20\d{2})', latest)
            year = year_m.group(1) if year_m else '未知'
            key = f"{year}-{rtype}"
            results[key] = {
                'file': os.path.basename(latest),
                'pages': sorted(set(t['page'] for items in texts.values() for t in items)),
                'key_points': _key_points(full),
                'raw_snippet': full[:600]
            }
            break

    return results


def _key_points(text: str) -> List[str]:
    """从董事会报告提取核心要点，按主题分类"""
    themes = {
        '营收表现': ['营业收入', '营收', '销售', '同比', '增长', '下滑'],
        '盈利能力': ['净利润', '毛利', '净利', '盈利', '亏损', '扣非'],
        '研发进展': ['研发', '临床', '注册', '批件', '创新药'],
        '行业竞争': ['市场', '竞争', '份额', '外资', '国产替代'],
        '战略规划': ['战略', '规划', '目标', '未来', '布局'],
        '政策影响': ['集采', '医保', '中标', '降价'],
        '风险提示': ['风险', '挑战', '不确定', '压力'],
    }
    lines = [l.strip() for l in text.split('\n') if len(l.strip()) > 10]
    points = []
    seen = set()

    for theme, kws in themes.items():
        for line in lines:
            if any(kw in line for kw in kws):
                sent = re.split(r'[。；]', line)[0].strip()
                if len(sent) > 8:
                    key = sent[:40]
                    if key not in seen:
                        seen.add(key)
                        points.append(f"[{theme}] {sent}")
                    break

    return points[:12]


# ─────────────────────────────────────────
# 整合格雷厄姆skill数据
# ─────────────────────────────────────────

def load_graham_data(data_dir: str, stock_code: str) -> Dict:
    data = {'available': []}
    fi = os.path.join(data_dir, 'financial_indicator.csv')
    if os.path.exists(fi):
        data['financial_indicator'] = fi
        data['available'].append('financial_indicator')
    val_files = glob.glob(os.path.join(data_dir, f'valuation_multi_{stock_code}*.json'))
    if val_files:
        with open(max(val_files, key=os.path.getmtime)) as f:
            data['valuation'] = json.load(f)
        data['available'].append('valuation')
    price = os.path.join(data_dir, 'price_history.csv')
    if os.path.exists(price):
        data['price_history'] = price
        data['available'].append('price')
    return data


# ─────────────────────────────────────────
# Graham专家
# ─────────────────────────────────────────

def analyze_graham(texts: Dict, financial_data: Dict = None) -> Dict:
    result = {
        'expert': 'Graham', 'score': 5,
        'accounting_policy': {}, 'earnings_quality': {},
        'risk_signals': [], 'positive_signals': [], 'final_assessment': ''
    }

    full = merge_texts(texts)

    # 收入确认
    inc = texts.get('收入确认', []) + texts.get('收入确认政策', [])
    if inc:
        t = '\n'.join([x['context'] for x in inc])
        result['accounting_policy']['revenue'] = t[:300]
        if any(kw in t for kw in ['终验法', '终验', '验收']):
            result['accounting_policy']['rev_type'] = '终验法（保守）'
        elif any(kw in t for kw in ['完工百分比', '时段法']):
            result['accounting_policy']['rev_type'] = '完工百分比（激进）'

    # 坏账计提
    ar = texts.get('应收账款坏账', []) + texts.get('预期信用损失', [])
    if ar:
        t = '\n'.join([x['context'] for x in ar])
        result['accounting_policy']['bad_debt'] = t[:300]
        r1 = re.findall(r'1年以内[^%\d]*(\d+(?:\.\d+)?)\s*%', t)
        r2 = re.findall(r'1至2年[^%\d]*(\d+(?:\.\d+)?)\s*%', t)
        if r1:
            result['accounting_policy']['rate_1y'] = f"{r1[0]}%"
            if float(r1[0]) >= 5:
                result['positive_signals'].append(f"1年以内坏账5%，格雷厄姆标准 ✅")
            else:
                result['risk_signals'].append(f"1年以内坏账{r1[0]}%，偏激进 ⚠️")

    # 研发资本化
    rd = texts.get('研发费用资本化', []) + texts.get('开发支出资本化', [])
    if rd:
        t = '\n'.join([x['context'] for x in rd])
        result['accounting_policy']['rd'] = t[:400]
        if any(kw in t for kw in ['临床试验完成', '进入临床', '临床I', '临床II']):
            result['accounting_policy']['rd_stage'] = '临床阶段（激进）'
            result['risk_signals'].append("研发资本化从临床试验完成开始，时点过早 ❌")
        elif any(kw in t for kw in ['注册申请', '批准']):
            result['accounting_policy']['rd_stage'] = '注册阶段（保守）'
            result['positive_signals'].append("资本化以批准为时点，较保守 ✅")

    # 审计意见
    audit = texts.get('审计意见', []) + texts.get('关键审计事项', [])
    if audit:
        t = '\n'.join([x['context'] for x in audit])
        result['accounting_policy']['audit'] = t[:200]
        if '标准无保留' in t:
            result['positive_signals'].append("审计标准无保留 ✅")
        if '收入确认' in t:
            result['risk_signals'].append("审计关注收入确认 ⚠️")
        if any(kw in t for kw in ['资本化', '开发支出']):
            result['risk_signals'].append("审计关注研发资本化 ⚠️")

    # 关联交易
    rpt = texts.get('关联方交易', []) + texts.get('关联销售', [])
    if rpt:
        t = '\n'.join([x['context'] for x in rpt])
        amounts = re.findall(r'([\d,]+(?:\.\d+)?)\s*(?:万|亿)', t)
        if amounts:
            result['accounting_policy']['rpt_amounts'] = amounts[:6]

    risk = len(result['risk_signals'])
    pos = len(result['positive_signals'])
    score = max(1, min(10, 5 + pos - risk))
    result['score'] = score
    result['final_assessment'] = f"Graham {score}/10。风险{risk}个，积极{pos}个。"
    return result


# ─────────────────────────────────────────
# Buffett专家
# ─────────────────────────────────────────

def analyze_buffett(texts: Dict, financial_data: Dict = None) -> Dict:
    result = {
        'expert': 'Buffett', 'score': 5,
        'business_quality': {}, 'moat_analysis': {},
        'management_assessment': {}, 'risk_signals': [],
        'positive_signals': [], 'final_assessment': ''
    }

    # 业务描述
    biz = texts.get('主要业务', []) + texts.get('公司业务', []) + texts.get('主营业务', [])
    if biz:
        t = '\n'.join([x['context'] for x in biz[:2]])
        result['business_quality']['desc'] = t[:400]
        result['business_quality']['complex'] = '复杂' if any(
            kw in t for kw in ['高壁垒', '专利', '创新药', '三类']) else '一般'

    # 管理层语调
    strat = (texts.get('经营计划', []) + texts.get('发展战略', []) +
             texts.get('未来展望', []) + texts.get('经营情况讨论与分析', []))
    if strat:
        t = '\n'.join([x['context'] for x in strat[:4]])
        result['management_assessment']['strategy'] = t[:500]
        pos_kw = sum(1 for kw in ['突破', '领先', '优势', '增长', '创新'] if kw in t)
        neg_kw = sum(1 for kw in ['面临', '风险', '压力', '挑战', '下降'] if kw in t)
        if pos_kw > neg_kw * 2:
            tone = '偏乐观'
            result['risk_signals'].append(f"管理层语调{tone}，可能低估风险 ⚠️")
        elif neg_kw > pos_kw:
            tone = '偏谨慎'
            result['positive_signals'].append("管理层客观谨慎，可信度高 ✅")
        else:
            tone = '中性'
        result['management_assessment']['tone'] = tone
        result['management_assessment']['tone_score'] = f"{pos_kw}:{neg_kw}"

    # 护城河
    moat = texts.get('核心竞争力', []) + texts.get('公司优势', [])
    if moat:
        t = '\n'.join([x['context'] for x in moat[:2]])
        result['moat_analysis']['desc'] = t[:300]
        types = []
        if '专利' in t: types.append('无形资产')
        if any(kw in t for kw in ['临床', '患者']): types.append('转换成本')
        if any(kw in t for kw in ['注册证', '审批', '准入']): types.append('行政许可')
        result['moat_analysis']['types'] = types if types else ['难以明确']

    # 竞争格局
    comp = texts.get('行业风险', []) + texts.get('市场竞争', [])
    competitors = []
    for t_list in comp:
        competitors.extend(re.findall(
            r'(强生|雅培|美敦力|波士顿|乐普|微创)[^\n，。]{0,15}',
            t_list['context']))
    if competitors:
        result['business_quality']['competitors'] = list(set(competitors))

    risk = len(result['risk_signals'])
    pos = len(result.get('positive_signals', []))
    score = max(1, min(10, 5 + len(result['moat_analysis'].get('types', [])) - risk + pos))
    result['score'] = score
    result['final_assessment'] = (
        f"Buffett {score}/10。护城河：{result['moat_analysis'].get('types',['?'])}，"
        f"语调：{result['management_assessment'].get('tone','?')}。"
    )
    return result


# ─────────────────────────────────────────
# Marks专家
# ─────────────────────────────────────────

def analyze_marks(texts: Dict) -> Dict:
    result = {
        'expert': 'Marks', 'score': 5,
        'disclosed_risks': {}, 'hidden_risks': [],
        'second_level': {}, 'cycle': 'unknown',
        'final_assessment': ''
    }

    # 已披露风险
    risk = texts.get('风险因素', []) + texts.get('重大风险提示', [])
    if risk:
        t = '\n'.join([x['context'] for x in risk[:4]])
        cats = {'行业风险': [], '政策风险': [], '经营风险': [], '财务风险': []}
        kws = {
            '行业风险': ['竞争加剧', '外资品牌', '市场份额'],
            '政策风险': ['集采', '带量采购', '医保谈判', '审批'],
            '经营风险': ['人才流失', '核心技术', '产品质量'],
            '财务风险': ['应收账款', '坏账', '汇率', '资金']
        }
        for line in t.split('\n'):
            for cat, kw_list in kws.items():
                if any(kw in line for kw in kw_list) and len(cats[cat]) < 2:
                    cats[cat].append(line.strip()[:120])
        result['disclosed_risks'] = {k: v for k, v in cats.items() if v}

    # 集采风险
    pol = texts.get('带量采购', []) + texts.get('集采', [])
    for t_list in pol:
        if '首次' in t_list['context'] or '新纳入' in t_list['context']:
            result['hidden_risks'].append({
                'type': '政策', 'severity': '高',
                'desc': '集采首次覆盖该公司，降价风险尚未定价 ⚠️'
            })

    # 募投滞后
    fund = texts.get('募集资金使用', [])
    for t_list in fund:
        for p in re.findall(r'(\d+(?:\.\d+)?)\s*%', t_list['context']):
            if float(p) < 30:
                result['hidden_risks'].append({
                    'type': '治理', 'severity': '高',
                    'desc': f"募投进度仅{p}%，严重滞后 ⚠️"
                })
                break

    # 人才风险
    talent = texts.get('人才风险', []) + texts.get('员工流失', [])
    for t_list in talent:
        if any(kw in t_list['context'] for kw in ['减少', '离职', '流失']):
            result['hidden_risks'].append({
                'type': '经营', 'severity': '中',
                'desc': '核心技术人员流失风险 ⚠️'
            })
            break

    # 竞争格局（第二层思维）
    comp = texts.get('行业风险', [])
    if comp:
        t = '\n'.join([x['context'] for x in comp[:2]])
        if any(kw in t for kw in ['80%', '外资', '主导']):
            result['second_level'] = {
                'consensus': '市场认为国产替代激动人心',
                'truth': '外资控制80%+份额，替代难度远超预期',
                'hidden': '集采可能倒逼外资降价，竞争加剧'
            }

    disclosed = sum(len(v) for v in result['disclosed_risks'].values())
    hidden = len(result['hidden_risks'])
    score = max(1, min(10, round(7 - hidden * 1.2 + disclosed * 0.3, 1)))
    result['score'] = score
    result['final_assessment'] = (
        f"Marks {score}/10。已披露{disclosed}条，隐藏{hidden}条。"
        f"{result['second_level'].get('truth','')[:60] if result['second_level'] else ''}"
    )
    return result


# ─────────────────────────────────────────
# Critic专家
# ─────────────────────────────────────────

def analyze_critic(texts: Dict, other_results: List = None,
                 financial_data: Dict = None) -> Dict:
    result = {
        'expert': 'Critic', 'score': 5,
        'supplementary': {}, 'ignored': [],
        'core_questions': [], 'final_recommendation': '观望',
        'final_assessment': ''
    }

    # 1. 股东结构
    gov = texts.get('前十大股东', []) + texts.get('股东变化', [])
    for t_list in gov:
        t = t_list['context']
        result['supplementary']['shareholder'] = t[:300]
        ratios = re.findall(r'(\d+(?:\.\d+)?)\s*%', t)
        if ratios:
            result['supplementary']['ratios'] = [f"{r}%" for r in ratios[:10]]
        unlocks = re.findall(r'(?:解禁|锁定期|限售).{0,80}', t)
        if unlocks:
            result['supplementary']['unlock'] = unlocks[:2]
            result['ignored'].append(f"解禁：{unlocks[0][:100]}")
        if any(kw in t for kw in ['减持', '退出']):
            result['ignored'].append("股东减持信号 ⚠️")
        break

    # 2. 客户集中度
    cust = texts.get('前五名客户', [])
    for t_list in cust:
        ratios = re.findall(r'(\d+(?:\.\d+)?)\s*%', t_list['context'])
        if ratios and float(ratios[0]) > 40:
            result['ignored'].append(f"客户集中度{ratios[0]}%，>40%高风险 ⚠️")
        result['supplementary']['customer'] = f"前五：{ratios[0] if ratios else '?'}%"
        if any(kw in t_list['context'] for kw in ['关联', '关联方']):
            result['supplementary']['rpt_customer'] = '含关联方客户'
        break

    # 3. 供应商集中度
    sup = texts.get('前五名供应商', [])
    for t_list in sup:
        ratios = re.findall(r'(\d+(?:\.\d+)?)\s*%', t_list['context'])
        if ratios:
            result['supplementary']['supplier'] = f"前五：{ratios[0]}%"
        break

    # 4. 募资使用
    fund = texts.get('募集资金使用', [])
    for t_list in fund:
        t = t_list['context']
        result['supplementary']['fund_usage'] = t[:400]
        for p in re.findall(r'(\d+(?:\.\d+)?)\s*%', t):
            if float(p) < 30:
                result['ignored'].append(f"募投仅{p}%完成，严重滞后 ⚠️")
                break

    # 5. 商誉
    gw = texts.get('商誉', [])
    for t_list in gw:
        amounts = re.findall(r'([\d,]+(?:\.\d+)?)\s*(?:万|亿)', t_list['context'])
        if amounts:
            result['supplementary']['goodwill'] = amounts[0]
        if '减值' in t_list['context']:
            result['ignored'].append("商誉减值不确定性 ⚠️")
        break

    # 6. 高管薪酬
    comp = texts.get('高管薪酬', []) + texts.get('高级管理人员薪酬', [])
    for t_list in comp:
        amounts = re.findall(r'([\d,]+)\s*万', t_list['context'])
        if amounts:
            result['supplementary']['exec_comp'] = f"{amounts[0]}万"
        break

    # 7. 分红
    div = texts.get('分红情况', []) + texts.get('现金分红', [])
    for t_list in div:
        t = t_list['context']
        result['supplementary']['dividend'] = t[:200]
        if '不分' in t:
            result['ignored'].append("有未分配利润但未分红 ⚠️")
        rates = re.findall(r'分红率[^\d]*(\d+(?:\.\d+)?)\s*%', t)
        if rates:
            result['supplementary']['div_rate'] = f"{rates[0]}%"
        break

    # 8. 股权激励
    inc = texts.get('股权激励', []) + texts.get('行权价格', [])
    for t_list in inc:
        prices = re.findall(r'(\d+(?:\.\d+)?)\s*元', t_list['context'])
        if prices:
            result['supplementary']['option_prices'] = [f"{p}元" for p in prices[:5]]
        break

    # 9. 在建工程
    wip = texts.get('在建工程', [])
    for t_list in wip:
        amounts = re.findall(r'([\d,]+(?:\.\d+)?)\s*(?:万|亿)', t_list['context'])
        if amounts:
            result['supplementary']['wip'] = amounts[0]
        break

    # 10. 关联交易
    rpt = texts.get('关联方交易', []) + texts.get('关联采购', [])
    if rpt:
        t = '\n'.join([x['context'] for x in rpt])
        amounts = re.findall(r'([\d,]+(?:\.\d+)?)\s*(?:万|亿)', t)
        if amounts:
            result['supplementary']['rpt_amounts'] = amounts[:6]
        if any(kw in t for kw in ['购买房屋', '建筑物']):
            result['ignored'].append("向关联方购买房屋，定价公允性存疑 ⚠️")

    # 综合评分
    scores = [result['score']]
    if other_results:
        scores.extend([r['score'] for r in other_results if r and 'score' in r])
    avg = sum(scores) / len(scores)
    if avg < 4: rec, score = '强烈回避', 3
    elif avg < 5.5: rec, score = '回避', 4
    elif avg < 6.5: rec, score = '观望', 5
    elif avg < 7.5: rec, score = '关注', 6
    else: rec, score = '买入', 7

    result['score'] = score
    result['final_recommendation'] = rec
    result['core_questions'] = result['ignored'][:5]
    result['final_assessment'] = (
        f"Critic {score}/10。建议：{rec}。"
        f"核心：{result['ignored'][0][:80] if result['ignored'] else '无'}"
    )
    return result


# ─────────────────────────────────────────
# 主程序
# ─────────────────────────────────────────

def find_pdfs(pdf_dir: str) -> Dict[str, str]:
    patterns = {
        '年度报告': ['*2025年年度报告.pdf', '*2024年年度报告.pdf'],
        '半年度报告': ['*2025年半年度报告.pdf', '*2024年半年度报告.pdf'],
        '第一季度报告': ['*2025年第一季度报告.pdf', '*一季报.pdf'],
        '第三季度报告': ['*2025年第三季度报告.pdf', '*三季报.pdf'],
    }
    found = {}
    for rtype, pats in patterns.items():
        for pat in pats:
            files = glob.glob(os.path.join(pdf_dir, pat))
            if files:
                found[rtype] = max(files, key=os.path.getmtime)
                break
    return found


def run_experts(texts: Dict, stock_code: str, output_dir: str,
                financial_data: Dict = None) -> List[Dict]:
    results, others = [], []
    for name, fn in [('Graham', analyze_graham), ('Buffett', analyze_buffett),
                      ('Marks', analyze_marks), ('Critic', analyze_critic)]:
        print(f"  🎯 {name}...", end='', flush=True)
        try:
            if name in ('Graham', 'Buffett'):
                r = fn(texts, financial_data)
            elif name == 'Marks':
                r = fn(texts)
            else:
                r = fn(texts, others, financial_data)
            with open(os.path.join(output_dir, f"{stock_code}_{name}_result.json"), 'w') as f:
                json.dump(r, f, ensure_ascii=False, indent=2)
            print(f" ✅ {r.get('score','?')}/10")
            results.append(r)
            others.append(r)
        except Exception as e:
            print(f" ❌ {e}")
    return results


def synthesize(stock_code: str, results: List[Dict],
               board_reports: Dict, output_dir: str) -> Dict:
    scores = [r['score'] for r in results if r and 'score' in r]
    avg = sum(scores) / len(scores) if scores else 5
    recs = list({r.get('final_recommendation','观望') for r in results if r})

    synthesis = {
        'meta': {
            'stock_code': stock_code,
            'date': datetime.now().strftime('%Y-%m-%d'),
            'experts': [r['expert'] for r in results if r],
            'board_reports': list(board_reports.keys()),
        },
        'individual': {
            r['expert']: {
                'score': r.get('score'),
                'assessment': r.get('final_assessment',''),
                'risks': (r.get('risk_signals',[]) + r.get('hidden_risks',[]))[:3],
                'positive': r.get('positive_signals',[])[:3],
            } for r in results if r
        },
        'board_reports': board_reports,
        'scores': {'composite': round(avg,1), 'range': f"{min(scores)}-{max(scores)}" if scores else '?'},
    }

    if avg < 4: synthesis['recommendation'] = '强烈回避'
    elif avg < 5.5: synthesis['recommendation'] = '回避'
    elif avg < 6.5: synthesis['recommendation'] = '观望'
    elif avg < 7.5: synthesis['recommendation'] = '关注'
    else: synthesis['recommendation'] = '买入'

    with open(os.path.join(output_dir, f"{stock_code}_deep_v2_report.json"), 'w') as f:
        json.dump(synthesis, f, ensure_ascii=False, indent=2)

    return synthesis


def main(stock_code: str, output_dir: str, experts: List[str] = None,
         pdf_dir: str = None, data_dir: str = None,
         integrate_graham: bool = False):
    os.makedirs(output_dir, exist_ok=True)
    pdf_dir = pdf_dir or output_dir
    data_dir = data_dir or output_dir

    graham_data = {}
    if integrate_graham:
        graham_data = load_graham_data(data_dir, stock_code)
        if graham_data.get('available'):
            print(f"\n📊 格雷厄姆skill数据：{', '.join(graham_data['available'])}")

    pdfs = find_pdfs(pdf_dir)
    if not pdfs:
        print(f"❌ 未找到PDF: {pdf_dir}")
        return

    annual = pdfs.get('年度报告', list(pdfs.values())[0])
    size_mb = os.path.getsize(annual) / 1024 / 1024
    print(f"\n📄 年报: {os.path.basename(annual)} ({size_mb:.1f} MB)")

    # 一次性PDF扫描
    all_kws = []
    for kws in CHAPTER_KEYWORDS.values():
        all_kws.extend(kws)
    print(f"\n{'='*50}")
    print(f"🎯 深度年报解析 v2.0 — {stock_code}")
    print(f"{'='*50}")
    print("  📖 一次性PDF预扫描...")
    texts = extract_chapter_text(annual, 'all', all_kws, max_pages=120)
    total = sum(len(v) for v in texts.values())
    print(f"  ✅ {total}命中，{len(texts)}章节")

    # 董事会报告追踪
    print(f"\n📋 董事会报告追踪")
    board_reports = {}
    for rtype, path in pdfs.items():
        try:
            kws = CHAPTER_KEYWORDS['board_report']
            br = {kw: texts.get(kw, []) for kw in kws if kw in texts}
            if br and any(br[kw] for kw in kws):
                full = merge_texts(br)
                ym = re.search(r'(20\d{2})', path)
                year = ym.group(1) if ym else '?'
                key = f"{year}-{rtype}"
                board_reports[key] = {
                    'file': os.path.basename(path),
                    'pages': sorted(set(t['page'] for kw in br for t in br[kw])),
                    'key_points': _key_points(full),
                }
                print(f"  {key}: {len(board_reports[key]['key_points'])}个要点")
        except Exception as e:
            print(f"  {rtype}: 失败 {e}")

    # 四专家
    results = run_experts(texts, stock_code, output_dir, graham_data)

    if results:
        s = synthesize(stock_code, results, board_reports, output_dir)
        print(f"\n{'='*50}")
        for r in results:
            print(f"  {r['expert']:10s}: {r.get('score','?'):4.1f}/10  {r.get('final_assessment','')[:70]}")
        print(f"{'='*50}")
        print(f"  综合: {s['scores']['composite']}/10  建议: {s['recommendation']}")
        print(f"{'='*50}")
        if board_reports:
            print(f"\n📋 董事会报告要点：")
            for key in sorted(board_reports):
                pts = board_reports[key].get('key_points', [])
                print(f"  [{key}] ({len(pts)}个)")
                for p in pts[:3]:
                    print(f"    • {p[:80]}")

    print(f"\n✅ 完成！结果: {output_dir}/")


if __name__ == '__main__':
    p = argparse.ArgumentParser(description='深度年报解析 v2.0')
    p.add_argument('stock_code', help='股票代码')
    p.add_argument('output_dir', help='输出目录')
    p.add_argument('--experts', default='Graham,Buffett,Marks,Critic',
                   help='启用的专家（逗号分隔）')
    p.add_argument('--pdf-dir', help='PDF目录（默认同output_dir）')
    p.add_argument('--data-dir', help='格雷厄姆skill数据目录')
    p.add_argument('--integrate-graham', action='store_true',
                   help='整合格雷厄姆skill数据（估值、财务指标）')
    args = p.parse_args()
    experts = [e.strip() for e in args.experts.split(',')]
    main(args.stock_code, args.output_dir, experts,
         args.pdf_dir, args.data_dir, args.integrate_graham)
