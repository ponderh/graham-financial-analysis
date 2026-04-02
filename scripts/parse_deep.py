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
# 三年财务趋势分析（新增模块）
# ─────────────────────────────────────────

def load_financial_trends(data_dir: str, stock_code: str) -> Optional[Dict]:
    """
    加载多年财务数据，计算趋势指标
    返回：{
        years: [2022, 2023, 2024, 2025],
        metrics: {eps: [...], roe: [...], ...},
        trends: {revenue_yoy: [...], net_profit_yoy: [...], ...},
        signals: {...}
    }
    """
    fi_annual = os.path.join(data_dir, 'financial_indicator_annual.csv')
    if not os.path.exists(fi_annual):
        return None

    try:
        import pandas as pd
        df = pd.read_csv(fi_annual)
        df = df.sort_values('日期').reset_index(drop=True)
    except Exception:
        return None

    years = [str(r)[:4] for r in df['日期']]

    # 提取关键指标（处理NaN）
    def safe(col):
        return [float(v) if pd.notna(v) else None for v in df[col]]

    metrics = {
        'eps': safe('摊薄每股收益(元)'),
        'roe': safe('净资产收益率(%)'),
        'net_margin': safe('销售净利率(%)'),
        'gross_margin': safe('销售毛利率(%)'),
        'debt_ratio': safe('资产负债率(%)'),
        'ocf_per_share': safe('每股经营性现金流(元)'),
        'bps': safe('每股净资产_调整后(元)'),
        'revenue_growth': safe('主营业务收入增长率(%)'),
        'profit_growth': safe('净利润增长率(%)'),
    }

    # 计算YoY变化
    def yoy(vals):
        result = []
        for i, v in enumerate(vals):
            if i == 0 or v is None or vals[i-1] is None or vals[i-1] == 0:
                result.append(None)
            else:
                result.append(round((v - vals[i-1]) / abs(vals[i-1]) * 100, 1))
        return result

    # 净现比
    net_cf_ratio = []
    for i in range(len(df)):
        eps = metrics['eps'][i]
        ocf = metrics['ocf_per_share'][i]
        if eps and eps > 0 and ocf is not None:
            net_cf_ratio.append(round(ocf / eps, 2))
        else:
            net_cf_ratio.append(None)

    # 趋势方向判断
    def trend(vals):
        valid = [v for v in vals if v is not None]
        if len(valid) < 2:
            return '→'
        first, last = valid[0], valid[-1]
        if last > first * 1.1:
            return '↗'
        elif last < first * 0.9:
            return '↘'
        return '→'

    signals = {}
    roe_vals = [v for v in metrics['roe'] if v is not None]
    if roe_vals:
        signals['roe_trend'] = trend(metrics['roe'])
        signals['roe_latest'] = roe_vals[-1]
    net_margin_vals = [v for v in metrics['net_margin'] if v is not None]
    if net_margin_vals:
        signals['net_margin_trend'] = trend(metrics['net_margin'])
        signals['net_margin_latest'] = net_margin_vals[-1]
    debt_vals = [v for v in metrics['debt_ratio'] if v is not None]
    if debt_vals:
        signals['debt_trend'] = trend(debt_vals)
        signals['debt_latest'] = debt_vals[-1]
        signals['debt_high'] = debt_vals[-1] > 60
    ncf_vals = [v for v in net_cf_ratio if v is not None]
    if ncf_vals:
        signals['cash_quality'] = '✅ 净现比>1' if ncf_vals[-1] > 1 else '⚠️ 净现比<1'
        signals['cash_quality_score'] = ncf_vals[-1]

    ocf_vals = [v for v in metrics['ocf_per_share'] if v is not None]
    if ocf_vals:
        signals['ocf_trend'] = trend(metrics['ocf_per_share'])
        signals['ocf_latest'] = ocf_vals[-1]

    return {
        'years': years,
        'metrics': metrics,
        'yoy': {
            'revenue': yoy([df['主营业务收入增长率(%)'].iloc[i] if pd.notna(df['主营业务收入增长率(%)'].iloc[i]) else None for i in range(len(df))]),
            'profit': yoy([df['净利润增长率(%)'].iloc[i] if pd.notna(df['净利润增长率(%)'].iloc[i]) else None for i in range(len(df))]),
        },
        'net_cf_ratio': net_cf_ratio,
        'signals': signals,
    }


# ─────────────────────────────────────────
# 估值维度分析（新增模块）
# ─────────────────────────────────────────

def analyze_valuation_dim(data_dir: str, stock_code: str) -> Dict:
    """
    整合估值数据 + 同行比较 → 估值水位判断
    """
    result = {
        'available': False,
        'current_price': None,
        'pe': None,
        'pb': None,
        'roe': None,
        'valuation_methods': {},
        'valuation_verdict': '',
        'verdict_level': 0,  # -2极度低估 ~ +5极度高估
        'peer_percentile': {},
        'recommendation': '',
        'buy_conditions': [],
        'sell_conditions': [],
        'catalysts': [],
    }

    # 加载估值JSON
    val_files = glob.glob(os.path.join(data_dir, f'valuation_multi_{stock_code}*.json'))
    if not val_files:
        return result

    try:
        with open(max(val_files, key=os.path.getmtime)) as f:
            val = json.load(f)
    except Exception:
        return result

    result['available'] = True
    result['current_price'] = val.get('current_price')
    km = val.get('key_metrics', {})
    eps = km.get('eps')
    bps = km.get('bps')
    if result['current_price'] and eps and eps > 0:
        result['pe'] = round(result['current_price'] / eps, 1)
    if result['current_price'] and bps and bps > 0:
        result['pb'] = round(result['current_price'] / bps, 2)
    result['roe'] = km.get('roe')

    # 整合各估值方法结果
    val_methods = val.get('valuations', {})
    current_price = result['current_price']
    method_verdicts = {}

    for method_name, v in val_methods.items():
        if not isinstance(v, dict):
            continue
        intrinsic = v.get('value', 0)
        if not intrinsic or intrinsic <= 0:
            continue
        ratio = current_price / intrinsic if current_price else None
        result['valuation_methods'][method_name] = {
            'intrinsic': round(intrinsic, 2),
            'ratio': round(ratio, 2) if ratio else None,
            'low': round(v.get('low', 0), 2),
            'high': round(v.get('high', 0), 2),
        }
        if ratio is not None:
            method_verdicts[method_name] = ratio

    # 综合判断
    if method_verdicts:
        avg_ratio = sum(method_verdicts.values()) / len(method_verdicts)
        result['avg_price_to_intrinsic'] = round(avg_ratio, 2)

        if avg_ratio > 5:
            result['verdict_level'] = 5
            result['valuation_verdict'] = f'极度高估（当前价是内在价值约{avg_ratio:.0f}倍）'
            result['recommendation'] = '卖出'
        elif avg_ratio > 3:
            result['verdict_level'] = 4
            result['valuation_verdict'] = f'显著高估（{avg_ratio:.1f}x）'
            result['recommendation'] = '卖出'
        elif avg_ratio > 1.5:
            result['verdict_level'] = 3
            result['valuation_verdict'] = f'偏高估（{avg_ratio:.1f}x）'
            result['recommendation'] = '回避'
        elif avg_ratio > 0.9:
            result['verdict_level'] = 2
            result['valuation_verdict'] = f'合理偏高（{avg_ratio:.1f}x）'
            result['recommendation'] = '观望'
        elif avg_ratio > 0.5:
            result['verdict_level'] = 0
            result['valuation_verdict'] = f'低估（{avg_ratio:.1f}x）'
            result['recommendation'] = '关注'
        else:
            result['verdict_level'] = -1
            result['valuation_verdict'] = f'极度低估（{avg_ratio:.1f}x）'
            result['recommendation'] = '强烈买入'

    # PE水位判断（独立于估值方法综合判断）
    if result['pe']:
        pe = result['pe']
        if pe > 100:
            result['pe_verdict'] = f'🔴 P/E={pe:.0f}x 极度高估（盈利质量无法支撑此估值）'
            result['verdict_level'] = max(result['verdict_level'], 5)
            result['recommendation'] = '卖出'
        elif pe > 60:
            result['pe_verdict'] = f'🟠 P/E={pe:.0f}x 极高（需高增长才能消化估值）'
            result['verdict_level'] = max(result['verdict_level'], 4)
        elif pe > 30:
            result['pe_verdict'] = f'🟡 P/E={pe:.0f}x 偏高'
        elif pe > 0:
            result['pe_verdict'] = f'🟢 P/E={pe:.0f}x 合理'

    # 加载同行比较
    peer_file = os.path.join(data_dir, f'peer_comparison_{stock_code}.json')
    if os.path.exists(peer_file):
        try:
            with open(peer_file) as f:
                peer = json.load(f)
            result['peer_percentile'] = peer.get('percentile_rankings', {})
            tm = peer.get('target_metrics', {})
            if tm:
                result['peer_pe'] = tm.get('pe')
        except Exception:
            pass

    # 买卖条件
    if result['pe'] and eps:
        result['buy_conditions'] = [
            f'PE降至30x以下（目标价：{round(30*eps, 1)}元）',
            f'PE降至20x以下（目标价：{round(20*eps, 1)}元）',
        ]
        result['sell_conditions'] = [
            f'PE超过100x（风险极高）或浮盈超过50%止盈',
        ]

    return result

# ─────────────────────────────────────────
# 多年盈利质量分析（v5新增）
# ─────────────────────────────────────────

def analyze_earnings_quality(data_dir: str) -> Dict:
    """
    多年度盈利质量深度分析
    1. 现金流质量（净现比趋势）
    2. 应收款项质量（应收账款天数趋势）
    3. 收入质量（经营现金流/营收趋势）
    4. Dupont ROE分解
    5. 运营杠杆
    """
    fi = os.path.join(data_dir, 'financial_indicator_annual.csv')
    if not os.path.exists(fi):
        return {'available': False}

    try:
        import pandas as pd
        df = pd.read_csv(fi)
        df = df.sort_values('日期').reset_index(drop=True)
    except Exception:
        return {'available': False}

    years = [str(r)[:4] for r in df['日期']]

    def safe(col):
        return [float(v) if pd.notna(v) else None for v in df[col]]

    # 原始指标
    ocf_ratio = safe('经营现金净流量对销售收入比率(%)')
    net_profit = safe('经营现金净流量与净利润的比率(%)')
    ar_days = safe('应收账款周转天数(天)')
    inv_days = safe('存货周转天数(天)')
    roe = safe('净资产收益率(%)')
    net_margin = safe('销售净利率(%)')
    asset_turn = safe('总资产周转率(次)')
    equity_ratio = safe('股东权益比率(%)')
    three_fee = safe('三项费用比重')
    revenue = safe('主营业务收入增长率(%)')

    # Dupont分解：ROE = 净利率 × 资产周转率 × 权益乘数
    dupont_analysis = []
    for i in range(len(df)):
        nm = net_margin[i]
        at = asset_turn[i]
        er = equity_ratio[i]
        if nm is not None and at is not None and er is not None and er > 0:
            equity_mult = 100 / er
            roe_dp = (nm / 100) * at * equity_mult * 100
            profit_contrib = nm / 100
            turnover_contrib = at
        else:
            roe_dp, profit_contrib, turnover_contrib = [None]*3
            equity_mult = None
        dupont_analysis.append({
            'year': years[i],
            'roe': round(roe_dp, 2) if roe_dp else None,
            'profit_margin_contrib': round(profit_contrib * 100, 2) if profit_contrib else None,
            'asset_turn_contrib': round(turnover_contrib, 3) if turnover_contrib else None,
            'equity_multiplier': round(equity_mult, 2) if equity_mult else None,
        })

    # 运营杠杆
    op_leverage = []
    for i in range(len(df)):
        fee = three_fee[i]
        rev_g = revenue[i]
        if fee is not None and rev_g is not None:
            if fee > 40 and rev_g < 15:
                verdict = '⚠️ 负向运营杠杆（费用率高+增速放缓）'
                signal = -1
            elif fee < 38 and rev_g and rev_g > 15:
                verdict = '✅ 正向运营杠杆（费用率下降+高速增长）'
                signal = 1
            else:
                verdict = '中性'
                signal = 0
            op_leverage.append({'verdict': verdict, 'signal': signal, 'fee_rate': round(fee,1), 'rev_growth': round(rev_g,1)})
        else:
            op_leverage.append({'verdict': '数据不足', 'signal': 0})

    # 应收款质量
    ar_signals = []
    for i in range(len(df)):
        days = ar_days[i]
        if days is not None:
            if days > 90:
                ar_signals.append('🔴 应收款>90天，回款风险高')
            elif days > 60:
                ar_signals.append('🟡 应收款60-90天，需关注')
            else:
                ar_signals.append('✅ 应收款周转正常')
        else:
            ar_signals.append('数据不足')

    # 盈利质量综合评分
    quality_scores = []
    for i in range(len(df)):
        score = 5
        ncf = net_profit[i] if i < len(net_profit) else None
        if ncf is not None:
            if ncf > 1: score += 1
            elif ncf < 0: score -= 2
        if ar_days[i] and ar_days[i] > 60: score -= 1
        if ar_days[i] and ar_days[i] > 90: score -= 1
        if roe[i] and roe[i] < 5: score -= 1
        if roe[i] and roe[i] > 15: score += 1
        quality_scores.append(max(1, min(10, score)))

    return {
        'available': True,
        'years': years,
        'dupont': dupont_analysis,
        'metrics': {
            'ocf_to_revenue': ocf_ratio,
            'net_cf_ratio': net_profit,
            'ar_days': ar_days,
            'inv_days': inv_days,
            'roe': roe,
            'net_margin': net_margin,
            'three_fee': three_fee,
            'revenue_growth': revenue,
        },
        'signals': {
            'ar_days_verdict': ar_signals,
            'op_leverage': op_leverage,
            'quality_scores': quality_scores,
        },
    }


# ─────────────────────────────────────────
# 管理层承诺兑现分析（v5新增）
# ─────────────────────────────────────────

def analyze_promise_vs_fulfillment(board_reports: Dict) -> Dict:
    """
    董事会报告年度对比：承诺 vs 兑现
    从各年董事会报告中提取管理层的经营目标承诺
    在次年报告中核查是否兑现
    """
    result = {
        'available': False,
        'promises': {},
        'fulfillment': {},
        'promise_count': 0,
        'fulfillment_rate': 0,
        'verdict': '',
    }

    if not board_reports:
        return result

    sorted_keys = sorted(board_reports.keys())
    if len(sorted_keys) < 2:
        return result

    result['available'] = True

    quant_kws = [
        r'增长\s*[到至]?\s*(\d+(?:\.\d+)?)%',
        r'(\d+(?:\.\d+)?)\s*%\s*增长',
        r'收入\s*[到至]?\s*(\d+[,，]?\d*)\s*(?:万|亿)',
        r'净利润\s*[到至]?\s*(\d+[,，]?\d*)\s*(?:万|亿)',
    ]

    all_promises = {}
    for key in sorted_keys:
        br = board_reports.get(key, {})
        pts = br.get('key_points', [])
        promises = []
        for pt in pts:
            if any(kw in pt for kw in ['计划', '目标', '预计', '努力', '争取']):
                quant_found = False
                for qpat in quant_kws:
                    m = re.search(qpat, pt)
                    if m:
                        promises.append({
                            'source': key, 'text': pt,
                            'quant_target': m.group(0), 'fulfilled': None,
                        })
                        quant_found = True
                        break
                if not quant_found:
                    promises.append({
                        'source': key, 'text': pt,
                        'quant_target': None, 'fulfilled': None,
                    })
        all_promises[key] = promises
        result['promise_count'] += len(promises)

    result['promises'] = {k: [{'text': p['text'], 'quant': p['quant_target']} for p in v]
                           for k, v in all_promises.items()}

    fulfill_kws = ['已实现', '已完成', '达成', '超额完成', '圆满完成', '如期']
    fail_kws = ['未完成', '未能', '未达', '低于', '不及']

    for i in range(len(sorted_keys) - 1):
        curr_key = sorted_keys[i]
        next_key = sorted_keys[i + 1]
        curr_promises = all_promises.get(curr_key, [])
        next_pts = board_reports.get(next_key, {}).get('key_points', [])
        next_text = ' '.join(next_pts)

        for p in curr_promises:
            if p['quant_target']:
                num_m = re.search(r'\d+(?:\.\d+)?', p['quant_target'])
                if num_m:
                    num_str = num_m.group(0)
                    if any(kw in next_text for kw in fulfill_kws) and num_str in next_text:
                        p['fulfilled'] = '✅'
                    elif any(kw in next_text for kw in fail_kws) and num_str in next_text:
                        p['fulfilled'] = '❌'
                    else:
                        p['fulfilled'] = '❓'

    fulfilled = sum(1 for pts in all_promises.values() for p in pts if p['fulfilled'] == '✅')
    failed = sum(1 for pts in all_promises.values() for p in pts if p['fulfilled'] == '❌')
    total = fulfilled + failed
    if total > 0:
        result['fulfillment_rate'] = round(fulfilled / total * 100, 0)
        result['verdict'] = f'承诺兑现率：{fulfilled}/{total}={result["fulfillment_rate"]:.0f}%'
    else:
        result['verdict'] = '无足够历史数据验证承诺兑现'

    result['fulfillment'] = {
        k: [{'text': p['text'], 'status': p['fulfilled']} for p in v]
        for k, v in all_promises.items()
    }

    return result



# ─────────────────────────────────────────
# Graham专家
# ─────────────────────────────────────────

def _dig_texts(texts_dict: Dict, keys: List[str], max_chars: int = 800) -> str:
    """从多个关键词组合文本，控制长度避免溢出"""
    parts = []
    for k in keys:
        for item in texts_dict.get(k, []):
            parts.append(item['context'][:max_chars])
    return '\n'.join(parts)


def _extract_rate(text: str, pattern: str) -> Optional[str]:
    """提取百分比数字"""
    m = re.search(pattern, text)
    return m.group(1) if m else None


def analyze_graham(texts: Dict, financial_data: Dict = None) -> Dict:
    """
    Graham专家 — 财务附注深度分析（6维度）
    维度1：收入确认政策（保守/激进判断 + 依据）
    维度2：坏账计提（1年以内 + 1-2年 + 3年以上提取率）
    维度3：研发资本化（资本化时点 + 比例 + 与上年对比）
    维度4：审计意见（关键审计事项数量 + 涉及科目）
    维度5：非经常性损益（金额 + 占净利比例 + 是否有水分）
    维度6：关联交易（金额 + 定价公允性判断）
    """
    result = {
        'expert': 'Graham', 'score': 5,
        'accounting_policy': {},
        'earnings_quality': {},
        'risk_signals': [],
        'positive_signals': [],
        'final_assessment': '',
        # 6维度展开
        'dimensions': {
            'revenue_recognition': {'policy': '', 'type': '', 'verdict': '', 'detail': ''},
            'bad_debt': {'rate_1y': '', 'rate_1_2y': '', 'rate_3y': '', 'verdict': ''},
            'rd_capitalization': {'timing': '', 'ratio': '', 'prior': '', 'verdict': ''},
            'audit_opinion': {'type': '', 'kam_count': 0, 'kam_items': [], 'verdict': ''},
            'non_recurring': {'amount': '', 'pct_of_net': '', 'quality': ''},
            'related_party': {'amount': '', 'pricing': '', 'verdict': ''},
        }
    }

    full = merge_texts(texts)

    # ── 维度1：收入确认 ──
    inc_text = _dig_texts(texts, ['收入确认', '收入确认政策', '会计政策和会计估计'])
    if inc_text:
        result['dimensions']['revenue_recognition']['detail'] = inc_text[:500]
        if any(kw in inc_text for kw in ['终验法', '终验', '验收完成后']):
            result['dimensions']['revenue_recognition']['policy'] = '终验法'
            result['dimensions']['revenue_recognition']['type'] = '保守'
            result['dimensions']['revenue_recognition']['verdict'] = '✅ 终验法：收入确认最保守，仅在交付完成后确认'
            result['positive_signals'].append("收入确认政策：终验法，交付完成前不确认收入 ✅")
        elif any(kw in inc_text for kw in ['完工百分比', '时段法', '履约进度', '投入法']):
            result['dimensions']['revenue_recognition']['policy'] = '完工百分比法'
            result['dimensions']['revenue_recognition']['type'] = '激进'
            result['dimensions']['revenue_recognition']['verdict'] = '⚠️ 完工百分比：需关注进度估计是否合理，存在操纵空间'
            result['risk_signals'].append("收入确认：使用完工百分比法，进度估计主观 ⚠️")
        elif any(kw in inc_text for kw in ['时点法', '控制权转移', '交付']):
            result['dimensions']['revenue_recognition']['policy'] = '时点法'
            result['dimensions']['revenue_recognition']['type'] = '中性'
            result['dimensions']['revenue_recognition']['verdict'] = '✅ 时点法：控制权转移时确认，标准做法'

    # ── 维度2：坏账计提 ──
    ar_text = _dig_texts(texts, ['应收账款坏账', '预期信用损失', '信用损失准备'])
    if ar_text:
        r1 = _extract_rate(ar_text, r'1年以内[^%\d]*(\d+(?:\.\d+)?)\s*%')
        r2 = _extract_rate(ar_text, r'1至2年[^%\d]*(\d+(?:\.\d+)?)\s*%')
        r3 = _extract_rate(ar_text, r'3年以[上年][^%\d]*(\d+(?:\.\d+)?)\s*%')
        result['dimensions']['bad_debt']['rate_1y'] = r1 or ''
        result['dimensions']['bad_debt']['rate_1_2y'] = r2 or ''
        result['dimensions']['bad_debt']['rate_3y'] = r3 or ''

        verdicts = []
        issues = []
        if r1:
            rate = float(r1)
            if rate >= 5:
                verdicts.append(f"1年以内{rate}% ≥ 格雷厄姆5%标准 ✅")
                result['positive_signals'].append(f"坏账计提1年以内{rate}%，符合格雷厄姆标准 ✅")
            elif rate >= 3:
                verdicts.append(f"1年以内{rate}% 处于3-5%区间，可接受")
            else:
                verdicts.append(f"1年以内{rate}% 明显偏低，计提不足 ⚠️")
                issues.append(f"坏账计提偏激进：1年以内仅{rate}%，可能低估应收账款风险")
        if r2 and float(r2) < 10:
            verdicts.append(f"1-2年{r2}% < 10%，计提不足 ⚠️")
            issues.append(f"1-2年坏账{r2}%，明显低于合理水平")
        result['dimensions']['bad_debt']['verdict'] = '；'.join(verdicts) if verdicts else '未找到详细分阶段计提率'
        result['risk_signals'].extend(issues)

    # ── 维度3：研发资本化 ──
    rd_text = _dig_texts(texts, ['研发费用资本化', '开发支出资本化', '资本化条件'])
    if rd_text:
        result['dimensions']['rd_capitalization']['detail'] = rd_text[:500]
        timing_map = {
            '临床试验完成': '临床完成（激进）',
            '进入临床': '进入临床（激进）',
            '临床I': '临床I期（激进）',
            '临床II': '临床II期（激进）',
            '注册申请': '注册申请（中性）',
            '获得批件': '获得批准（保守）',
            '批准文号': '获批（保守）',
        }
        found_timing = None
        for kw, label in timing_map.items():
            if kw in rd_text:
                found_timing = label
                break
        if found_timing:
            result['dimensions']['rd_capitalization']['timing'] = found_timing
            if '激进' in found_timing:
                result['dimensions']['rd_capitalization']['verdict'] = f"⚠️ 资本化时点过早（{found_timing[1:]}），可将研发支出提前确认为资产"
                result['risk_signals'].append(f"研发资本化时点：{found_timing}，时点过早，存在美化利润可能 ⚠️")
            else:
                result['dimensions']['rd_capitalization']['verdict'] = f"✅ 资本化时点保守（{found_timing[1:]}）"
                result['positive_signals'].append(f"研发资本化时点：{found_timing}，相对保守 ✅")
        ratio = _extract_rate(rd_text, r'资本化[^%\d]*(\d+(?:\.\d+)?)\s*%')
        if ratio:
            result['dimensions']['rd_capitalization']['ratio'] = f"{ratio}%"

    # ── 维度4：审计意见 ──
    audit_text = _dig_texts(texts, ['审计意见', '关键审计事项'])
    if audit_text:
        kam_items = []
        if '标准无保留' in audit_text:
            result['dimensions']['audit_opinion']['type'] = '标准无保留意见'
            result['dimensions']['audit_opinion']['verdict'] = '✅ 标准无保留：最清洁的审计意见'
            result['positive_signals'].append("审计意见：标准无保留 ✅")
        elif '保留意见' in audit_text:
            result['dimensions']['audit_opinion']['type'] = '保留意见'
            result['dimensions']['audit_opinion']['verdict'] = '❌ 保留意见：存在重大不确定性'
            result['risk_signals'].append("审计意见：保留意见 ❌")
        elif '无法表示' in audit_text:
            result['dimensions']['audit_opinion']['type'] = '无法表示意见'
            result['dimensions']['audit_opinion']['verdict'] = '❌ 无法表示意见：审计范围受限'
            result['risk_signals'].append("审计意见：无法表示意见 ❌")

        for kw in ['收入确认', '研发资本化', '应收账款', '商誉', '存货', '固定资产']:
            if kw in audit_text:
                kam_items.append(kw)
        result['dimensions']['audit_opinion']['kam_count'] = len(kam_items)
        result['dimensions']['audit_opinion']['kam_items'] = kam_items
        if kam_items:
            result['dimensions']['audit_opinion']['verdict'] += f'；关键审计事项涉及：{"、".join(kam_items)}（共{len(kam_items)}项）'
            for item in kam_items:
                if item not in ['固定资产', '存货']:  # 排除相对正常的
                    result['risk_signals'].append(f"审计重点关注：{item} ⚠️")

    # ── 维度5：非经常性损益 ──
    nri_text = _dig_texts(texts, ['非经常性损益'])
    if nri_text:
        amounts = re.findall(r'([\d,]+(?:\.\d+)?)\s*万', nri_text)
        if amounts:
            result['dimensions']['non_recurring']['amount'] = f"{amounts[0]}万"
        net_m = re.search(r'净利润[^\d]*([\d,]+(?:\.\d+)?)\s*万', nri_text)
        nri_m = re.search(r'非经常性损益[^\d]*([\d,]+(?:\.\d+)?)\s*万', nri_text)
        if net_m and nri_m:
            try:
                net = float(net_m.group(1).replace(',', ''))
                nri = float(nri_m.group(1).replace(',', ''))
                if net > 0:
                    pct = nri / net * 100
                    result['dimensions']['non_recurring']['pct_of_net'] = f"{pct:.1f}%"
                    if pct > 30:
                        result['dimensions']['non_recurring']['quality'] = '⚠️ 占比偏高，盈利质量存疑'
                        result['risk_signals'].append(f"非经常性损益占净利润{pct:.1f}% > 30%，盈利质量偏低 ⚠️")
                    elif pct < 10:
                        result['dimensions']['non_recurring']['quality'] = '✅ 占比低，盈利主要来自主业'
                        result['positive_signals'].append(f"非经常性损益仅占{pct:.1f}%，主业盈利质量高 ✅")
            except:
                pass

    # ── 维度6：关联交易 ──
    rpt_text = _dig_texts(texts, ['关联方交易', '关联销售', '关联采购', '关联担保'])
    if rpt_text:
        amounts = re.findall(r'([\d,]+(?:\.\d+)?)\s*(?:万|亿)', rpt_text)
        if amounts:
            result['dimensions']['related_party']['amount'] = '、'.join(amounts[:4])
        if any(kw in rpt_text for kw in ['购买房屋', '建筑物', '资产转让']):
            result['dimensions']['related_party']['pricing'] = '涉及资产转让，需关注定价公允性'
            result['risk_signals'].append("关联交易：涉及资产转让，定价公允性存疑 ⚠️")
        elif not rpt_text.strip():
            result['dimensions']['related_party']['verdict'] = '未发现异常关联交易'
        else:
            result['dimensions']['related_party']['verdict'] = '需结合金额和性质综合判断'

    # 综合评分
    risk = len(result['risk_signals'])
    pos = len(result['positive_signals'])
    score = max(1, min(10, round(6 + pos * 0.5 - risk * 1.0, 1)))
    result['score'] = score

    # 汇总评估
    verdict_lines = []
    for dim_name, dim in result['dimensions'].items():
        if dim.get('verdict', ''):
            verdict_lines.append(dim['verdict'])
    verdict_text = '；'.join(verdict_lines[:4])

    result['final_assessment'] = (
        f"Graham {score}/10。"
        f"风险信号{len(result['risk_signals'])}个，积极信号{pos}个。"
        f"{verdict_text[:120]}"
    )
    return result


# ─────────────────────────────────────────
# Buffett专家
# ─────────────────────────────────────────

def analyze_buffett(texts: Dict, financial_data: Dict = None) -> Dict:
    """
    Buffett专家 — 商业本质深度分析
    1. 护城河：多维度验证（专利/临床数据/注册证/转换成本/行政许可）
    2. 管理层语调：语义分析（乐观/谨慎/客观），行动 vs 言语一致性
    3. 竞争格局：主要对手识别 + 市场份额推断
    4. FCF文字推断：从经营现金流描述推断自由现金流质量
    """
    result = {
        'expert': 'Buffett', 'score': 5,
        'business_quality': {},
        'moat_analysis': {},
        'management_assessment': {},
        'competitors': [],
        'fcf_quality': {},
        'risk_signals': [],
        'positive_signals': [],
        'final_assessment': '',
    }

    full = merge_texts(texts)

    # ── 1. 业务描述与复杂度 ──
    biz_text = _dig_texts(texts, ['主要业务', '公司业务', '主营业务', '公司经营范围'])
    if biz_text:
        result['business_quality']['desc'] = biz_text[:600]
        high_barrier = any(kw in biz_text for kw in ['高壁垒', '专利保护', '创新药', '三类医疗器械', '进入壁垒'])
        result['business_quality']['high_barrier'] = high_barrier
        result['business_quality']['complex'] = '高壁垒业务' if high_barrier else '一般竞争业务'

    # ── 2. 护城河多维度验证 ──
    moat_text = _dig_texts(texts, ['核心竞争力', '公司优势', '技术优势', '竞争实力', '行业地位'])
    moat_types = []
    moat_evidence = []

    if moat_text:
        result['moat_analysis']['raw'] = moat_text[:400]

        # 类型1：无形资产（专利、独家品种）
        patents = re.findall(r'(\d+)\s*项(?:发明)?专利|(\d+)\s*个(?:发明)?专利', moat_text)
        if any(kw in moat_text for kw in ['专利', '发明专利', '实用新型', '独家', '原研']):
            moat_types.append('无形资产（专利/独家）')
            count = re.search(r'(\d+)\s*项', moat_text)
            moat_evidence.append(f"专利：{count.group(1) if count else '若干'}项" if count else "拥有专利")

        # 类型2：转换成本（临床绑定、患者黏性）
        if any(kw in moat_text for kw in ['临床', '患者', '医生', '手术', '长期使用', '黏性']):
            moat_types.append('转换成本（临床黏性）')
            moat_evidence.append("临床使用形成患者黏性")

        # 类型3：行政许可（三类注册证、医疗器械）
        reg_count = re.findall(r'(\d+)\s*张|(\d+)\s*个(?:注册证|证)', moat_text)
        if any(kw in moat_text for kw in ['注册证', '三类', '医疗器械注册', '准入', 'GMP']):
            moat_types.append('行政许可壁垒')
            reg = re.search(r'(\d+)\s*(?:张|个).*?注册证|注册证.*?(\d+)', moat_text)
            moat_evidence.append(f"注册证：{reg.group(1) if reg else '若干'}张")

        # 类型4：规模经济
        if any(kw in moat_text for kw in ['规模', '产能', '市场份额', '领先']):
            moat_types.append('规模经济')
            moat_evidence.append("具备规模优势")

    result['moat_analysis']['types'] = moat_types if moat_types else ['护城河不明确']
    result['moat_analysis']['evidence'] = moat_evidence

    # 护城河宽度判断
    moat_width = len(moat_types)
    if moat_width >= 3:
        result['moat_analysis']['width'] = '宽护城河'
        result['positive_signals'].append(f"拥有{moat_width}种护城河（{'、'.join(moat_types)}），壁垒坚固 ✅")
    elif moat_width == 2:
        result['moat_analysis']['width'] = '中等护城河'
        result['positive_signals'].append(f"拥有2种护城河（{'、'.join(moat_types)}），具备一定壁垒")
    elif moat_width == 1:
        result['moat_analysis']['width'] = '窄护城河'
        result['risk_signals'].append(f"仅1种护城河（{moat_types[0]}），竞争激烈时脆弱 ⚠️")
    else:
        result['moat_analysis']['width'] = '护城河不明'
        result['risk_signals'].append("护城河不明确，难以抵御竞争对手 ⚠️")

    # ── 3. 管理层语调深度分析 ──
    strat_text = _dig_texts(texts, [
        '经营情况讨论与分析', '董事会报告', '发展战略', '经营计划',
        '未来展望', '未来发展展望', '公司战略'
    ], max_chars=1000)

    tone_detail = {'乐观': 0, '谨慎': 0, '客观': 0}
    tone_signals = []

    if strat_text:
        result['management_assessment']['raw_text_sample'] = strat_text[:800]

        # 乐观信号词
        optimistic_phrases = {
            '大幅增长': +2, '突破': +1, '领先': +1, '第一': +1, '最优': +1,
            '强劲增长': +2, '高速增长': +2, '远超': +2, '历史最好': +2,
            '全面增长': +1, '显著提升': +1, '大幅提升': +2,
        }
        # 谨慎/悲观信号词
        cautious_phrases = {
            '面临压力': -1, '面临挑战': -1, '竞争加剧': -1, '存在不确定性': -2,
            '下降趋势': -2, '大幅下降': -2, '持续承压': -2, '显著下降': -2,
            '风险加大': -2, '困难': -1, '压力': -1,
        }

        tone_score = 0
        for phrase, weight in {**optimistic_phrases, **cautious_phrases}.items():
            count = strat_text.count(phrase)
            tone_score += count * weight
            if count > 0:
                tone_signals.append(f"{'+' if weight > 0 else ''}{weight}×「{phrase}」({count}次)")

        result['management_assessment']['tone_signals'] = tone_signals[:10]

        if tone_score >= 3:
            tone = '过度乐观'
            result['management_assessment']['verdict'] = '⚠️ 语调过度乐观，管理层可能选择性披露好消息，决策者应保持警惕'
            result['risk_signals'].append("管理层语调过度乐观（多家券商研报也常用类似词汇），可信度打折 ⚠️")
        elif tone_score > 0:
            tone = '偏乐观'
            result['management_assessment']['verdict'] = '略偏乐观，但总体在合理范围'
            result['risk_signals'].append("管理层语调偏乐观，注意分辨承诺与实际兑现能力 ⚠️")
        elif tone_score < -2:
            tone = '过度谨慎'
            result['management_assessment']['verdict'] = '⚠️ 语调过于谨慎，可能存在隐瞒或信心不足'
        else:
            tone = '客观中性'
            result['management_assessment']['verdict'] = '✅ 语调客观中性，管理层披露可信度高'
            result['positive_signals'].append("管理层语调客观中性，表述谨慎可信 ✅")

        result['management_assessment']['tone'] = tone
        result['management_assessment']['tone_score'] = tone_score

    # ── 4. 竞争格局 ──
    comp_text = _dig_texts(texts, ['行业风险', '行业格局', '竞争格局', '市场竞争', '主要对手'], max_chars=600)
    known_competitors = {
        '强生': 'Johnson & Johnson', '雅培': 'Abbott', '美敦力': 'Medtronic',
        '波士顿科学': 'Boston Scientific', '乐普医疗': '乐普', '微创医疗': '微创',
        '辉瑞': 'Pfizer', '诺华': 'Novartis', '阿斯利康': 'AstraZeneca',
        'GE': 'GE Healthcare', '西门子': 'Siemens Healthineers',
        '罗氏': 'Roche', '碧迪': 'Becton Dickinson',
    }
    found_competitors = []
    for cn, en in known_competitors.items():
        if cn in comp_text:
            found_competitors.append(cn)
    result['competitors'] = found_competitors
    if found_competitors:
        result['business_quality']['top_competitors'] = found_competitors
        result['business_quality']['competition_fierce'] = len(found_competitors) >= 2
        if len(found_competitors) >= 2:
            result['risk_signals'].append(f"面临{found_competitors[0]}等强劲对手竞争，市场格局激烈 ⚠️")

    # ── 5. FCF文字推断（从现金流章节） ──
    cfo_text = _dig_texts(texts, ['经营活动现金流', '经营活动产生的现金流量'], max_chars=500)
    if cfo_text:
        result['fcf_quality']['raw'] = cfo_text[:300]
        # 从文字推断FCF质量
        if any(kw in cfo_text for kw in ['现金流充裕', '现金流良好', '净流入']):
            result['fcf_quality']['verdict'] = '✅ 经营现金流为正，资金周转健康'
            result['positive_signals'].append("经营现金流为正，现金流管理健康 ✅")
        elif any(kw in cfo_text for kw in ['现金流为负', '净流出', '资金紧张']):
            result['fcf_quality']['verdict'] = '⚠️ 经营现金流为负，存在资金压力'
            result['risk_signals'].append("经营现金流为负，FCF质量差 ⚠️")

    # ── 综合评分 ──
    risk = len(result['risk_signals'])
    pos = len(result.get('positive_signals', []))
    moat_score = moat_width if moat_width > 0 else 0.5
    tone_penalty = 1 if '乐观' in result['management_assessment'].get('tone', '') else 0
    score = max(1, min(10, round(5 + moat_score * 0.5 - risk * 0.7 + pos * 0.3 - tone_penalty, 1)))
    result['score'] = score

    result['final_assessment'] = (
        f"Buffett {score}/10。"
        f"护城河：{result['moat_analysis'].get('width','?')}（{', '.join(result['moat_analysis'].get('types',['?']))}）。"
        f"语调：{result['management_assessment'].get('tone','?')}（{"正" if result['management_assessment'].get('tone_score',0) > 0 else '负'}{abs(result['management_assessment'].get('tone_score',0))}）。"
        f"主要对手：{', '.join(found_competitors) if found_competitors else '未识别'}。"
    )
    return result


# ─────────────────────────────────────────
# Marks专家
# ─────────────────────────────────────────

def analyze_marks(texts: Dict) -> Dict:
    """
    Marks专家 — 风险识别与第二层思维
    核心方法：对比「市场共识」vs「隐藏真相」
    每个已披露风险 → 反向推断被忽视的另一面
    每个好消息 → 寻找背后的代价或风险
    """
    result = {
        'expert': 'Marks', 'score': 5,
        'disclosed_risks': {},  # 分类：行业/政策/经营/财务/法律
        'hidden_risks': [],     # 含「市场共识 vs 隐藏真相」结构
        'second_level_thinking': [],  # 深度反向推断结果
        'cycle_position': {},
        'final_assessment': '',
    }

    full = merge_texts(texts)

    # ══ 第一步：提取已披露风险（5分类） ══
    risk_text = _dig_texts(texts, ['风险因素', '重大风险提示', '风险揭示', '风险提示'], max_chars=1500)
    if risk_text:
        cats = {
            '行业风险': [],
            '政策风险': [],
            '经营风险': [],
            '财务风险': [],
            '法律合规': [],
        }
        cat_kws = {
            '行业风险': ['竞争加剧', '市场饱和', '外资品牌', '市场份额', '替代品', '技术迭代'],
            '政策风险': ['集采', '带量采购', '医保谈判', '审批风险', '合规', '监管', '两票制', '一票制'],
            '经营风险': ['人才流失', '核心技术', '产品质量', '客户集中', '供应商集中', '产能', '募投'],
            '财务风险': ['应收账款', '坏账', '汇率', '资金', '商誉减值', '存货', '流动性'],
            '法律合规': ['诉讼', '仲裁', '处罚', '召回', '违规', '许可', '知识产权'],
        }
        for line in risk_text.split('\n'):
            line = line.strip()
            if len(line) < 10:
                continue
            for cat, kw_list in cat_kws.items():
                if any(kw in line for kw in kw_list) and len(cats[cat]) < 3:
                    cats[cat].append(line[:150])
                    break
        result['disclosed_risks'] = {k: v for k, v in cats.items() if v}

    # ══ 第二步：第二层思维 — 每个风险找反向推断 ══
    # 集采风险：市场共识 vs 隐藏真相
    pol_text = _dig_texts(texts, ['带量采购', '集采', '医保谈判', '中标价格'], max_chars=600)
    if pol_text:
        if any(kw in pol_text for kw in ['首次', '新纳入', '即将']):
            result['hidden_risks'].append({
                'type': '政策',
                'severity': '🔴 高',
                'market_consensus': '市场认为集采是政策红利，快速放量',
                'hidden_truth': '首次集采中标价格大幅下降，短期内营收和利润双杀，以价换量不成立',
                'evidence': '首次纳入集采，价格降幅未知但历史上普遍超50%',
                'price_impact': '⚠️ 短期内集采价格降幅可能超预期，2024-2025年财报将承压',
            })
        elif any(kw in pol_text for kw in ['续约', '中标']):
            result['hidden_risks'].append({
                'type': '政策',
                'severity': '🟡 中',
                'market_consensus': '市场认为续约稳定，格局明朗',
                'hidden_truth': '续约价格可能继续下降，竞争对手以更低价格抢份额',
                'evidence': '历次集采续约价格均持续下降',
                'price_impact': '⚠️ 续约不代表价格稳定，竞争格局变化仍存风险',
            })

    # 募投滞后：市场共识 vs 隐藏真相
    fund_text = _dig_texts(texts, ['募集资金使用', '募资用途', '募投项目'], max_chars=600)
    for t_list in texts.get('募集资金使用', []):
        progress_m = re.findall(r'(\d+(?:\.\d+)?)\s*%', t_list['context'])
        for p_str in progress_m:
            p = float(p_str)
            if p < 30:
                result['hidden_risks'].append({
                    'type': '治理',
                    'severity': '🔴 高',
                    'market_consensus': '市场认为IPO募资项目正在推进，成长性可期',
                    'hidden_truth': f'3年仅完成{p}%进度，募资早已到账却迟迟不开工，说明管理层缺乏有效资金运用能力，资产使用效率极低',
                    'evidence': f'募集资金项目进度{p}%，严重低于预期',
                    'management_signal': '⚠️ 募投滞后往往反映管理层执行力弱或市场已变，需警惕',
                })
            elif p < 60:
                result['hidden_risks'].append({
                    'type': '治理',
                    'severity': '🟡 中',
                    'market_consensus': '市场认为募投项目进展正常',
                    'hidden_truth': f'3年仅完成{p}%进度，说明项目需求减弱或管理层重点已转移',
                    'evidence': f'募集资金项目进度{p}%，低于预期',
                    'management_signal': '⚠️ 需关注项目可行性是否已发生变化',
                })

    # 研发进展：市场共识 vs 隐藏真相
    rd_text = _dig_texts(texts, ['研发进展', '研发管线', '临床试验', '注册申请'], max_chars=600)
    if rd_text:
        if any(kw in rd_text for kw in ['研发费用下降', '研发投入减少', '研发人员减少']):
            result['hidden_risks'].append({
                'type': '经营',
                'severity': '🔴 高',
                'market_consensus': '市场认为研发在推进，有管线价值',
                'hidden_truth': '研发投入下降=未来管线竞争力削弱，短期内减少费用美化利润，但中长期成长性受损',
                'evidence': '研发费用同比下降',
                'long_term_signal': '⚠️ 研发投入减少预示未来产品线竞争力下降',
            })
        if any(kw in rd_text for kw in ['临床失败', '未获批', '被否']):
            result['hidden_risks'].append({
                'type': '经营',
                'severity': '🔴 高',
                'market_consensus': '市场往往忽视单一临床失败的真实影响',
                'hidden_truth': '该管线失败意味着前期投入打水漂，且该适应症竞争格局已变',
                'evidence': '存在临床试验未达预期的情况',
                'capital_impact': '⚠️ 失败管线占用研发资源，影响其他管线进度',
            })

    # 客户集中度：市场共识 vs 隐藏真相
    cust_text = _dig_texts(texts, ['前五名客户', '客户集中度'], max_chars=400)
    if cust_text:
        ratios = re.findall(r'(\d+(?:\.\d+)?)\s*%', cust_text)
        if ratios and float(ratios[0]) > 35:
            result['hidden_risks'].append({
                'type': '经营',
                'severity': '🔴 高',
                'market_consensus': '市场认为大客户=稳定收入来源',
                'hidden_truth': f'第一大客户占比{ratios[0]}%，一旦该客户流失或减少采购，营收将断崖式下跌',
                'evidence': f'客户集中度{ratios[0]}%，超过安全线',
                'customer_risk': f'⚠️ {ratios[0]}%集中度 = 该客户拥有强议价权，可能持续压价',
            })

    # 人才风险：市场共识 vs 隐藏真相
    talent_text = _dig_texts(texts, ['员工流失', '人才风险', '核心技术', '高级管理人员'], max_chars=400)
    if talent_text:
        if any(kw in talent_text for kw in ['减少', '离职', '流失', '变动']):
            result['hidden_risks'].append({
                'type': '经营',
                'severity': '🟡 中',
                'market_consensus': '市场认为核心人员离职是个别现象，不影响大局',
                'hidden_truth': '医药/医疗器械公司核心竞争力=核心人员，离职往往是更深层问题的表现（激励不足、战略分歧）',
                'evidence': '存在人员变动或核心技术流失迹象',
                'culture_signal': '⚠️ 高管或核心技术人员离职可能预示内部治理问题',
            })

    # 股东变化：市场共识 vs 隐藏真相
    sh_text = _dig_texts(texts, ['前十大股东', '股东变化', '股份变动', '股东减持'], max_chars=500)
    if sh_text:
        if any(kw in sh_text for kw in ['减持', '退出', '减少']):
            result['hidden_risks'].append({
                'type': '股东结构',
                'severity': '🔴 高',
                'market_consensus': '市场认为大股东减持是正常市场行为',
                'hidden_truth': '内部人最了解公司真实价值，大股东减持=当前股价被高估，或对未来缺乏信心',
                'evidence': '存在大股东或机构减持行为',
                'insider_signal': '⚠️ 大股东减持是重要反向指标，不应被忽视',
            })
        if any(kw in sh_text for kw in ['解禁', '限售股']):
            result['hidden_risks'].append({
                'type': '股东结构',
                'severity': '🟡 中',
                'market_consensus': '市场对解禁压力认知不足',
                'hidden_truth': '解禁股大规模上市将稀释流通股东权益，尤其是成本极低的原始股',
                'evidence': '存在限售股解禁',
                'supply_signal': '⚠️ 解禁前后股价往往承压，流通股比例增加',
            })

    # 竞争格局：市场共识 vs 隐藏真相
    comp_text = _dig_texts(texts, ['行业风险', '行业格局', '竞争格局', '行业地位'], max_chars=600)
    if comp_text:
        if any(kw in comp_text for kw in ['80%', '外资主导', '外资品牌']):
            result['hidden_risks'].append({
                'type': '行业',
                'severity': '🔴 高',
                'market_consensus': '市场认为国产替代空间巨大，是超级成长股逻辑',
                'hidden_truth': '外资品牌控制80%+份额，凭借医生使用习惯、售后、学术推广牢牢掌控终端，国产替代难度远超预期，需要漫长时间',
                'evidence': '市场由外资主导，份额超80%',
                'substitution_hurdle': '⚠️ 医疗器械替代需要完成临床验证、医生培训、学术推广，远非「纳入医保」即可完成',
            })

    # ══ 第三步：综合评分（基于隐藏风险数量和严重程度）══
    hidden_high = sum(1 for r in result['hidden_risks'] if r['severity'] in ('🔴 高', '高'))
    hidden_mid = sum(1 for r in result['hidden_risks'] if r['severity'] in ('🟡 中', '中'))
    disclosed_count = sum(len(v) for v in result['disclosed_risks'].values())

    # Marks公式：基础分 - 高风险×1.5 - 中风险×0.8 + 已披露风险加成
    score = max(1, min(10, round(7 - hidden_high * 1.5 - hidden_mid * 0.8 + disclosed_count * 0.15, 1)))
    result['score'] = score

    # 隐藏风险汇总
    hidden_summary = [f"{r['type']}:{r['severity']}" for r in result['hidden_risks'][:5]]

    result['final_assessment'] = (
        f"Marks {score}/10。"
        f"已披露{disclosed_count}条，隐藏{len(result['hidden_risks'])}条"
        f"（🔴高{hidden_high}个/🟡中{hidden_mid}个）。"
        f"核心：{result['hidden_risks'][0]['hidden_truth'][:60] if result['hidden_risks'] else '无明显隐藏风险'}。"
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
               board_reports: Dict, output_dir: str,
               data_dir: str = None) -> Dict:
    """
    综合四位专家结果 + 估值维度 + 财务趋势 → 最终决策
    评分权重：Graham×0.35, Marks×0.30, Critic×0.20, Buffett×0.15
    """
    # 专家评分
    scores = [r['score'] for r in results if r and 'score' in r]
    weights = {'Graham': 0.35, 'Buffett': 0.15, 'Marks': 0.30, 'Critic': 0.20}
    weighted_sum = 0
    for r in results:
        if r and 'score' in r:
            w = weights.get(r['expert'], 0.25)
            weighted_sum += r['score'] * w

    avg = sum(scores) / len(scores) if scores else 5  # 简单平均兜底
    composite = round(weighted_sum, 1)

    # 加载估值维度
    valuation = analyze_valuation_dim(data_dir or output_dir, stock_code)

    # 加载财务趋势
    trends = load_financial_trends(data_dir or output_dir, stock_code)

    # 加载盈利质量分析（v5新增）
    earnings_quality = analyze_earnings_quality(data_dir or output_dir)

    # 管理层承诺兑现分析（v5新增）
    promise_analysis = analyze_promise_vs_fulfillment(board_reports)

    # 最终推荐（综合专家分 + 估值）
    if valuation.get('available') and valuation.get('verdict_level', 0) > 0:
        # 估值高估/极度高估 → 降低推荐
        adjustment = valuation['verdict_level'] * 0.3
        final_score = max(1, composite - adjustment)
    elif valuation.get('verdict_level', 0) < 0:
        final_score = min(10, composite + 0.5)
    else:
        final_score = composite

    if final_score < 4: recommendation = '强烈回避'
    elif final_score < 5: recommendation = '回避'
    elif final_score < 6: recommendation = '观望'
    elif final_score < 7: recommendation = '关注'
    else: recommendation = '买入'

    synthesis = {
        'meta': {
            'stock_code': stock_code,
            'date': datetime.now().strftime('%Y-%m-%d'),
            'experts': [r['expert'] for r in results if r],
            'board_reports': list(board_reports.keys()),
            'data_sources': {
                'pdf_annual': True,
                'valuation': valuation.get('available', False),
                'financial_trends': trends is not None,
            }
        },
        'individual': {
            r['expert']: {
                'score': r.get('score'),
                'assessment': r.get('final_assessment',''),
                'risks': (r.get('risk_signals',[]) + [x.get('hidden_truth','') for x in r.get('hidden_risks',[])])[:3],
                'positive': r.get('positive_signals',[])[:3],
            } for r in results if r
        },
        'board_reports': board_reports,
        'scores': {
            'composite': round(avg, 1),
            'weighted': round(composite, 1),
            'final': round(final_score, 1),
            'range': f"{min(scores)}-{max(scores)}" if scores else '?',
            'weights_used': weights,
        },
        'valuation': {
            'current_price': valuation.get('current_price'),
            'pe': valuation.get('pe'),
            'pb': valuation.get('pb'),
            'roe': valuation.get('roe'),
            'verdict': valuation.get('valuation_verdict', ''),
            'verdict_level': valuation.get('verdict_level', 0),
            'avg_ratio': valuation.get('avg_price_to_intrinsic'),
            'methods': valuation.get('valuation_methods', {}),
            'pe_verdict': valuation.get('pe_verdict', ''),
            'peer_percentile': valuation.get('peer_percentile', {}),
        },
        'earnings_quality': None,  # v5新增
        'promise_analysis': None,  # v5新增
        'decision': {
            'recommendation': recommendation,
            'final_score': round(final_score, 1),
            'buy_conditions': valuation.get('buy_conditions', []),
            'sell_conditions': valuation.get('sell_conditions', []),
            'catalysts': [],  # 来自董事会报告/公告的催化剂
            'bull_case': [],   # 买入逻辑
            'bear_case': [],   # 卖出逻辑
        },
    }

    # 财务趋势摘要
    if trends:
        sig = trends.get('signals', {})
        synthesis['financial_trends'] = {
            'years': trends['years'],
            'eps': trends['metrics']['eps'],
            'roe': trends['metrics']['roe'],
            'net_margin': trends['metrics']['net_margin'],
            'net_cf_ratio': trends['net_cf_ratio'],
            'signals': sig,
        }
    synthesis['earnings_quality'] = earnings_quality if earnings_quality.get('available') else None
    synthesis['promise_analysis'] = promise_analysis if promise_analysis.get('available') else None

    # 多空逻辑汇总
    for r in results:
        if not r:
            continue
        if r['expert'] == 'Buffett' and r.get('positive_signals'):
            synthesis['decision']['bull_case'].extend(r['positive_signals'][:2])
        if r['expert'] == 'Marks' and r.get('hidden_risks'):
            for hr in r['hidden_risks'][:3]:
                synthesis['decision']['bear_case'].append(hr.get('hidden_truth', '')[:100])
        if r['expert'] == 'Critic' and r.get('ignored'):
            synthesis['decision']['bear_case'].extend([x for x in r['ignored'][:2]])

    # 管理质量信号（来自承诺兑现分析）
    if promise_analysis and promise_analysis.get('available'):
        if promise_analysis.get('fulfillment_rate', 0) >= 80:
            synthesis['decision']['bull_case'].append(
                f"管理层承诺兑现率{promise_analysis['fulfillment_rate']:.0f}%（>80%），执行力强 ✅"
            )
        elif promise_analysis.get('fulfillment_rate', 0) < 50:
            synthesis['decision']['bear_case'].append(
                f"管理层承诺兑现率{promise_analysis['fulfillment_rate']:.0f}%（<50%），执行力弱 ⚠️"
            )

    # 盈利质量信号
    if earnings_quality and earnings_quality.get('available'):
        eq = earnings_quality
        yrs = eq['years']
        qs = eq['signals'].get('quality_scores', [])
        if qs:
            latest_q = qs[-1] if qs else 5
            if latest_q >= 7:
                synthesis['decision']['bull_case'].append(
                    f"盈利质量评分{latest_q}/10（优秀），现金流健康 ✅"
                )
            elif latest_q <= 4:
                synthesis['decision']['bear_case'].append(
                    f"盈利质量评分{latest_q}/10（偏差），现金流质量存疑 ⚠️"
                )

    # 催化剂（从董事会报告推断）
    for key, br in board_reports.items():
        pts = br.get('key_points', [])
        for p in pts:
            if any(kw in p for kw in ['临床', '获批', '注册', '新品', '中标']):
                synthesis['decision']['catalysts'].append(p)

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

    # ── 多年PDF扫描 ──
    pdfs = find_pdfs(pdf_dir)
    if not pdfs:
        print(f"❌ 未找到PDF: {pdf_dir}")
        return

    # ── 扫描所有可用年份的所有PDF ──
    # 重新找所有PDF（不限年份）
    all_annual_pdfs = sorted(
        glob.glob(os.path.join(pdf_dir, '*年年度报告.pdf')),
        key=os.path.getmtime, reverse=True
    )
    all_texts = {}  # {年份: {关键词: [上下文...]}}
    pdf_years = {}  # {年份: 路径}

    for pdf_path in all_annual_pdfs:
        ym = re.search(r'(20\d{2})', pdf_path)
        year = ym.group(1) if ym else 'unknown'
        if year in all_texts:
            continue  # 已扫描过该年份，跳过
        size_mb = os.path.getsize(pdf_path) / 1024 / 1024
        print(f"\n📄 [{year}年度报告] {os.path.basename(pdf_path)} ({size_mb:.1f} MB)")
        all_kws = []
        for kws in CHAPTER_KEYWORDS.values():
            all_kws.extend(kws)
        texts = extract_chapter_text(pdf_path, 'all', all_kws, max_pages=120)
        total = sum(len(v) for v in texts.values())
        print(f"  ✅ {total}命中，{len(texts)}章节")
        if texts:
            all_texts[year] = texts
            pdf_years[year] = pdf_path

    # 也扫描半年报/季报（如果有）
    other_types = {
        '半年度报告': glob.glob(os.path.join(pdf_dir, '*年半年度报告.pdf')),
        '第一季度报告': glob.glob(os.path.join(pdf_dir, '*第一季度报告.pdf')),
        '第三季度报告': glob.glob(os.path.join(pdf_dir, '*第三季度报告.pdf')),
    }
    for rtype, files in other_types.items():
        for pdf_path in sorted(files, key=os.path.getmtime, reverse=True)[:1]:  # 每类最多1份
            ym = re.search(r'(20\d{2})', pdf_path)
            year = ym.group(1) if ym else 'unknown'
            if year in all_texts:
                continue
            size_mb = os.path.getsize(pdf_path) / 1024 / 1024
            print(f"\n📄 [{year}{rtype}] {os.path.basename(pdf_path)} ({size_mb:.1f} MB)")
            all_kws = []
            for kws in CHAPTER_KEYWORDS.values():
                all_kws.extend(kws)
            texts = extract_chapter_text(pdf_path, 'all', all_kws, max_pages=80)
            total = sum(len(v) for v in texts.values())
            print(f"  ✅ {total}命中，{len(texts)}章节")
            if texts:
                all_texts[year] = texts
                pdf_years[year] = pdf_path

    if not all_texts:
        print("❌ 没有成功解析任何PDF")
        return

    # 用最新年份做四专家分析
    latest_year = max(all_texts.keys())
    texts = all_texts[latest_year]

    print(f"\n{'='*50}")
    print(f"🎯 深度年报解析 v3.0 — {stock_code}（共扫描{len(all_texts)}个财报）")
    print(f"{'='*50}")

    # 董事会报告追踪（从多年PDF提取）
    print(f"\n📋 董事会报告追踪（{len(all_texts)}年）")
    board_reports = {}
    year_to_rtype = {v: k for k, v in pdf_years.items()}  # 文件路径→年份
    for year, year_texts in sorted(all_texts.items()):
        kws = CHAPTER_KEYWORDS['board_report']
        br = {kw: year_texts.get(kw, []) for kw in kws if kw in year_texts}
        if br and any(br[kw] for kw in kws):
            full = merge_texts(br)
            key = f"{year}-年度报告"
            board_reports[key] = {
                'file': os.path.basename(pdf_years.get(year, '')),
                'pages': sorted(set(t['page'] for kw in br for t in br[kw])),
                'key_points': _key_points(full),
            }
            print(f"  {key}: {len(board_reports[key]['key_points'])}个要点")

    # 四专家（用最新年份PDF）
    results = run_experts(texts, stock_code, output_dir, graham_data)

    if results:
        s = synthesize(stock_code, results, board_reports, output_dir, data_dir)
        print(f"\n{'='*50}")
        for r in results:
            print(f"  {r['expert']:10s}: {r.get('score','?'):4.1f}/10  {r.get('final_assessment','')[:70]}")
        print(f"{'='*50}")
        val = s.get('valuation', {})
        if val.get('available'):
            print(f"  💰 估值: PE={val.get('pe','?')}x  |  {val.get('verdict','?')}")
        print(f"  综合: {s['scores']['final']}/10  建议: {s['decision']['recommendation']}")
        print(f"{'='*50}")
        if board_reports:
            print(f"\n📋 董事会报告要点：")
            for key in sorted(board_reports):
                pts = board_reports[key].get('key_points', [])
                print(f"  [{key}] ({len(pts)}个)")
                for p in pts[:3]:
                    print(f"    • {p[:80]}")
        # 决策摘要
        dec = s.get('decision', {})
        if dec:
            print(f"\n📊 决策条件：")
            for cond in dec.get('buy_conditions', [])[:2]:
                print(f"  🟢 买入条件: {cond}")
            for cond in dec.get('sell_conditions', [])[:2]:
                print(f"  🔴 卖出条件: {cond}")

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
