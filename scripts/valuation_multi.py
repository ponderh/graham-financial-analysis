#!/usr/bin/env python3
"""
多估值体系计算模块
包含7种估值方法：Graham Number / EPV / Buffett IV / DCF / PEG / DDM / EV/EBITDA

用法: python3 valuation_multi.py <股票代码> <数据目录>
"""

import sys
import os
import json
import math

# ─────────────────────────────────────────
# 辅助函数
# ─────────────────────────────────────────

def safe_div(a, b, default=None):
    """安全除法，避免除零错误"""
    try:
        return a / b if b != 0 else default
    except (TypeError, ValueError):
        return default


def weighted_avg(data, weights):
    """加权平均"""
    s = sum(d * w for d, w in zip(data, weights) if d is not None and w is not None)
    w_sum = sum(w for d, w in zip(data, weights) if d is not None and w is not None)
    return safe_div(s, w_sum)


# ─────────────────────────────────────────
# 估值方法实现
# ─────────────────────────────────────────

def graham_number(eps, bps, roe=None, rf=0.03):
    """
    格雷厄姆数
    保守版: V = √(22.5 × EPS × BPS)
    成长调整版（ROE>15%）: V = √(22.5 × EPS × BPS × (1 + 0.5×(ROE-rf)))
    """
    if not eps or not bps or eps <= 0 or bps <= 0:
        return None, None
    
    conservative = math.sqrt(22.5 * eps * bps)
    
    growth_adj = conservative
    if roe and roe > 0.15:
        factor = 1 + 0.5 * (roe - rf)
        growth_adj = math.sqrt(22.5 * eps * bps * factor)
    
    return conservative, growth_adj


def earnings_power_value(eps, net_cash_ratio, rf=0.03, risk_premium=0.03):
    """
    Earnings Power Value (EPV)
    V = EPS / r，其中 r = 无风险利率 + 风险溢价
    修正：V_adj = EPV × min(净现比/1.0, 1.0)
    A股适用 r ≈ 6%（rf=3% + 风险溢价3%）
    """
    if not eps or eps <= 0:
        return None
    
    r = rf + risk_premium  # 6%
    epv = eps / r
    
    # 净现比修正（盈利质量打折）
    if net_cash_ratio is not None:
        quality_factor = min(net_cash_ratio / 1.0, 1.0)
        epv_adj = epv * quality_factor
    else:
        epv_adj = epv
    
    return epv_adj


def buffett_intrinsic_value(fcf_per_share, growth_rate, wacc=0.08, terminal_g=0.03):
    """
    巴菲特内在价值（简化两阶段模型）
    V = Σ(OEn / (1+r)^n) + TV / (1+r)^n
    
    参数:
    - fcf_per_share: 每股自由现金流估算（用经营CF近似）
    - growth_rate: 前5年预期增速（小数，如0.12表示12%）
    - wacc: 股权要求收益率（8%）
    - terminal_g: 永续增长率（取无风险利率上限3%）
    """
    if not fcf_per_share or fcf_per_share <= 0:
        return None, None
    
    # 永续价值 TV = FCF_n × (1+g) / (WACC - g)
    # 5年后永续，TV折现到现值
    # 第一阶段：5年高增长
    
    total_pv = 0
    fcf_estimates = []
    
    for year in range(1, 6):
        fcf_n = fcf_per_share * (1 + growth_rate) ** year
        pv = fcf_n / (1 + wacc) ** year
        total_pv += pv
        fcf_estimates.append(fcf_n)
    
    # 永续价值（从第5年末开始）
    tv = fcf_estimates[-1] * (1 + terminal_g) / (wacc - terminal_g)
    tv_pv = tv / (1 + wacc) ** 5
    
    intrinsic_value = total_pv + tv_pv
    
    return intrinsic_value, None


def dcf_two_stage(fcf_per_share, stage1_years=5, stage1_growth=0.12, wacc=0.08, terminal_g=0.03):
    """
    两阶段DCF模型
    
    第一阶段（高增长期）：stage1_years年，每年增长stage1_growth
    第二阶段（永续期）：永续增长terminal_g
    """
    if not fcf_per_share or fcf_per_share <= 0:
        return None, None
    
    total_pv = 0
    
    # 第一阶段折现
    for year in range(1, stage1_years + 1):
        fcf_n = fcf_per_share * (1 + stage1_growth) ** year
        pv = fcf_n / (1 + wacc) ** year
        total_pv += pv
    
    # 第二阶段永续价值
    fcf_stage1_end = fcf_per_share * (1 + stage1_growth) ** stage1_years
    tv = fcf_stage1_end * (1 + terminal_g) / (wacc - terminal_g)
    tv_pv = tv / (1 + wacc) ** stage1_years
    
    intrinsic_value = total_pv + tv_pv
    
    # 敏感性分析：WACC ±1%
    wacc_low = wacc - 0.01
    wacc_high = wacc + 0.01
    
    iv_low = None
    iv_high = None
    try:
        tv_low = fcf_stage1_end * (1 + terminal_g) / (wacc_low - terminal_g)
        total_low = sum(
            fcf_per_share * (1 + stage1_growth)**y / (1 + wacc_low)**y 
            for y in range(1, stage1_years + 1)
        ) + tv_low / (1 + wacc_low) ** stage1_years
        
        tv_high = fcf_stage1_end * (1 + terminal_g) / (wacc_high - terminal_g)
        total_high = sum(
            fcf_per_share * (1 + stage1_growth)**y / (1 + wacc_high)**y 
            for y in range(1, stage1_years + 1)
        ) + tv_high / (1 + wacc_high) ** stage1_years
        
        iv_low = min(total_low, total_high)
        iv_high = max(total_low, total_high)
    except (ValueError, ZeroDivisionError):
        pass
    
    return intrinsic_value, (iv_low, iv_high)


def peg_ratio(pe_ttm, expected_growth_rate):
    """
    PEG = PE / (增速×100)
    G因子 = PE / 增速 = 市盈率相对于增速的倍数
    格雷厄姆标准：G因子 < 15（PE=15, 增速=100%=1时）
    即 PEG < 1 表示相对低估
    """
    if not pe_ttm or not expected_growth_rate or expected_growth_rate <= 0:
        return None
    
    peg = pe_ttm / (expected_growth_rate * 100)
    target_pe = expected_growth_rate * 100 * 1.0  # PEG=1合理估值
    implied_value = pe_ttm / (expected_growth_rate * 100) * pe_ttm  # 反推股价
    
    return peg


def dividend_discount_model(dps, required_return=0.08, growth_rate=0.03):
    """
    DDM = D / (r - g)
    仅适用于高分红股（分红率>30%）
    """
    if not dps or dps <= 0 or growth_rate >= required_return:
        return None
    
    v = dps / (required_return - growth_rate)
    return v


def ev_ebdita(ebitda, ev_multiple=None, industry_avg_multiple=8.0):
    """
    EV/EBITDA估值
    EV = EBITDA × EV/EBITDA倍数
    股价 = (EV - 净债务) / 总股本
    """
    if not ebitda or ebitda <= 0:
        return None
    
    multiple = ev_multiple or industry_avg_multiple
    ev = ebitda * multiple
    return ev  # 返回企业价值，需减去净债务得到股权价值


# ─────────────────────────────────────────
# 主计算逻辑
# ─────────────────────────────────────────

def load_financial_data(stock_code, data_dir):
    """从数据目录加载财务数据"""
    
    # 尝试读取综合财务指标
    indicator_file = os.path.join(data_dir, "financial_indicator_annual.csv")
    balance_file = os.path.join(data_dir, "balance_sheet.csv")
    cashflow_file = os.path.join(data_dir, "cashflow_sheet.csv")
    price_file = os.path.join(data_dir, "price_history.csv")
    
    data = {}
    
    # 读取财务指标
    if os.path.exists(indicator_file):
        import pandas as pd
        df = pd.read_csv(indicator_file)
        if '日期' in df.columns:
            df = df.sort_values('日期', ascending=False)
            latest = df.iloc[0]
            
            eps_col = '摊薄每股收益(元)'
            data['eps'] = float(latest.get(eps_col, latest.get('摊薄每股收益', 0)))
            data['bps'] = float(latest.get('每股净资产_调整后(元)', latest.get('每股净资产_调整前(元)', 0)))
            data['roe'] = float(latest.get('净资产收益率(%)', 0)) / 100
            data['net_margin'] = float(latest.get('销售净利率(%)', 0)) / 100
            data['gross_margin'] = float(latest.get('销售毛利率(%)', 0)) / 100
            data['debt_ratio'] = float(latest.get('资产负债率(%)', 0)) / 100
            
            # 净现比（经营CF/净利润）
            cashflow_df = pd.read_csv(cashflow_file) if os.path.exists(cashflow_file) else None
            if cashflow_df is not None and len(cashflow_df) > 0:
                cf_latest = cashflow_df.sort_values('日期', ascending=False).iloc[0]
                operating_cf = cf_latest.get('经营活动产生的现金流量净额', 0)
                net_profit = latest.get('净利润', latest.get('归属于母公司净利润', 0))
                if operating_cf and net_profit and float(net_profit) != 0:
                    data['net_cash_ratio'] = float(operating_cf) / float(net_profit)
            
            # 3年平均ROE
            if len(df) >= 2:
                data['roe_avg3'] = df['净资产收益率(%)'].head(3).mean() / 100
            else:
                data['roe_avg3'] = data['roe']
    
    # 读取股价（获取当前价格）
    if os.path.exists(price_file):
        import pandas as pd
        price_df = pd.read_csv(price_file)
        if '日期' in price_df.columns:
            price_df = price_df.sort_values('日期', ascending=False)
            data['current_price'] = float(price_df.iloc[0].get('收盘', 0))
    
    # 估算FCF（经营CF近似，用3年平均）
    if os.path.exists(cashflow_file):
        import pandas as pd
        cf_df = pd.read_csv(cashflow_file)
        if '经营活动产生的现金流量净额' in cf_df.columns:
            cf_vals = cf_df['经营活动产生的现金流量净额'].dropna()
            if len(cf_vals) >= 1:
                data['avg_operating_cf'] = float(cf_vals.head(3).mean())
    
    # 读取公司信息（获取总股本）
    info_file = os.path.join(data_dir, "company_info.csv")
    if os.path.exists(info_file):
        import pandas as pd
        info_df = pd.read_csv(info_file)
        if len(info_df) > 0:
            data['total_shares'] = float(info_df.iloc[0].get('总股本', 0))
    
    return data


def main(stock_code, data_dir="."):
    print(f"\n{'='*60}")
    print(f"多估值体系计算 — {stock_code}")
    print(f"{'='*60}\n")
    
    data = load_financial_data(stock_code, data_dir)
    
    if not data:
        print("❌ 未找到财务数据，请先运行 data_fetch.py 采集数据")
        return
    
    # 提取参数
    eps = data.get('eps')
    bps = data.get('bps')
    roe = data.get('roe')
    net_cash_ratio = data.get('net_cash_ratio')
    current_price = data.get('current_price', 0)
    fcf_per_share = data.get('avg_operating_cf', 0) / data.get('total_shares', 1) if data.get('avg_operating_cf') else None
    
    if not eps or eps <= 0:
        print("❌ EPS数据无效，无法计算")
        return
    
    print(f"当前股价: {current_price:.2f}元")
    print(f"EPS: {eps:.3f}元 | BPS: {bps:.3f}元 | ROE: {roe*100:.2f}% | 净现比: {net_cash_ratio:.2f}" if net_cash_ratio else f"EPS: {eps:.3f} | ROE: {roe*100:.2f}%")
    print()
    
    results = {}
    
    # ── ① Graham Number ──
    print("① Graham Number（格雷厄姆数）")
    g_con, g_growth = graham_number(eps, bps, roe)
    if g_con:
        results['Graham保守版'] = {'low': g_con, 'mid': g_con, 'high': g_con, 'value': g_con}
        g_con_pct = (current_price / g_con - 1) * 100 if g_con else None
        print(f"   保守版: {g_con:.2f}元 | 当前价溢价: {g_con_pct:+.1f}%" if g_con_pct else f"   保守版: {g_con:.2f}元")
    if g_growth and g_growth != g_con:
        results['Graham成长版'] = {'low': g_growth, 'mid': g_growth, 'high': g_growth, 'value': g_growth}
        g_growth_pct = (current_price / g_growth - 1) * 100
        print(f"   成长版: {g_growth:.2f}元 | 当前价溢价: {g_growth_pct:+.1f}%")
    print()
    
    # ── ② EPV ──
    print("② Earnings Power Value（盈利权力值）")
    epv = earnings_power_value(eps, net_cash_ratio)
    if epv:
        results['EPV'] = {'low': epv * 0.85, 'mid': epv, 'high': epv * 1.15, 'value': epv}
        epv_pct = (current_price / epv - 1) * 100
        print(f"   EPV: {epv:.2f}元 | 当前价溢价: {epv_pct:+.1f}%")
    print()
    
    # ── ③ Buffett IV ──
    print("③ Buffett Intrinsic Value（巴菲特内在价值）")
    # 假设未来5年增速 = 近期净利率改善趋势，保守取5%
    growth_est = min(roe * 0.3, 0.15) if roe else 0.08  # 保守估计
    buffett_iv, _ = buffett_intrinsic_value(fcf_per_share or eps, growth_est)
    if buffett_iv:
        results['Buffett IV'] = {'low': buffett_iv * 0.8, 'mid': buffett_iv, 'high': buffett_iv * 1.2, 'value': buffett_iv}
        buffett_pct = (current_price / buffett_iv - 1) * 100
        print(f"   内在价值: {buffett_iv:.2f}元（假设增速{growth_est*100:.1f}%） | 当前价溢价: {buffett_pct:+.1f}%")
    print()
    
    # ── ④ DCF ──
    print("④ Two-Stage DCF（两阶段折现现金流）")
    # 使用近3年净利润增速均值估算
    dcf_iv, dcf_range = dcf_two_stage(fcf_per_share or eps, stage1_growth=growth_est)
    if dcf_iv:
        results['DCF两阶段'] = {
            'low': dcf_range[0] if dcf_range else dcf_iv * 0.85,
            'mid': dcf_iv,
            'high': dcf_range[1] if dcf_range else dcf_iv * 1.15,
            'value': dcf_iv
        }
        dcf_pct = (current_price / dcf_iv - 1) * 100
        low_pct = (current_price / results['DCF两阶段']['low'] - 1) * 100 if results['DCF两阶段']['low'] else None
        high_pct = (current_price / results['DCF两阶段']['high'] - 1) * 100 if results['DCF两阶段']['high'] else None
        print(f"   DCF估值: {dcf_iv:.2f}元 | 区间: [{results['DCF两阶段']['low']:.2f}, {results['DCF两阶段']['high']:.2f}]")
        print(f"   当前价溢价: {dcf_pct:+.1f}%")
    print()
    
    # ── ⑤ PEG ──
    print("⑤ PEG Ratio（市盈率相对增长比）")
    # 假设未来3年增速 = ROE × 派息率（简化）
    payout_ratio = 0.57  # 永新分红率57%，其他股票可调整
    implied_growth = payout_ratio * roe if roe else 0.10
    pe_ttm = current_price / eps if eps and eps > 0 else None
    peg = peg_ratio(pe_ttm, implied_growth) if pe_ttm else None
    if peg is not None:
        target_pe = implied_growth * 100  # PEG=1时的合理PE
        target_price = target_pe * eps
        results['PEG'] = {
            'low': target_price * 0.8,
            'mid': target_price,
            'high': target_price * 1.2,
            'value': target_price
        }
        peg_pct = (current_price / target_price - 1) * 100 if target_price else None
        print(f"   PEG: {peg:.2f}（<1低估，>1.5高估）")
        print(f"   隐含合理价: {target_price:.2f}元（基于{implied_growth*100:.1f}%增速假设）")
        print(f"   当前价溢价: {peg_pct:+.1f}%" if peg_pct else "")
    print()
    
    # ── ⑥ DDM（仅高分红股）──
    print("⑥ Dividend Discount Model（股息折现模型）")
    # 需要实际分红数据，此处用EPS×分红率估算
    dps_est = eps * payout_ratio if eps and payout_ratio else None
    ddm_v = dividend_discount_model(dps_est, required_return=0.08, growth_rate=0.03) if dps_est else None
    if ddm_v:
        results['DDM'] = {'low': ddm_v * 0.85, 'mid': ddm_v, 'high': ddm_v * 1.15, 'value': ddm_v}
        ddm_pct = (current_price / ddm_v - 1) * 100
        print(f"   DDM估值: {ddm_v:.2f}元 | 当前价溢价: {ddm_pct:+.1f}%")
    print()
    
    # ── 汇总表格 ──
    print("=" * 70)
    print("估值结果汇总")
    print("=" * 70)
    print(f"{'方法':<18} {'下限':>8} {'中值':>8} {'上限':>8} {'当前价':>8} {'位置':>8}")
    print("-" * 70)
    
    all_values = []
    for name, v in results.items():
        low = v.get('low', v['value'])
        mid = v['value']
        high = v.get('high', v['value'])
        all_values.extend([low, mid, high])
        
        if current_price and mid > 0:
            position = (current_price / mid - 1) * 100
            pos_str = f"溢价{position:+.1f}%" if position > 0 else f"折价{abs(position):.1f}%"
        else:
            pos_str = "N/A"
        
        print(f"{name:<18} {low:>8.2f} {mid:>8.2f} {high:>8.2f} {current_price:>8.2f} {pos_str:>8}")
    
    print("-" * 70)
    
    # 综合估值区间
    valid_values = [v for v in all_values if v and v > 0]
    if valid_values:
        low_est = sorted(valid_values)[len(valid_values)//4]  # 25分位
        mid_est = sorted(valid_values)[len(valid_values)//2]  # 中位
        high_est = sorted(valid_values)[3*len(valid_values)//4]  # 75分位
        
        print(f"\n📊 综合估值区间: [{low_est:.2f}, {mid_est:.2f}, {high_est:.2f}]元")
        print(f"   当前价: {current_price:.2f}元", end="")
        if current_price and mid_est > 0:
            overall_pct = (current_price / mid_est - 1) * 100
            print(f" → {overall_pct:+.1f}%（{'溢价' if overall_pct > 0 else '折价'}）")
        print()
        
        if current_price and low_est:
            print(f"安全边际分析:")
            print(f"  相比区间下限({low_est:.2f}元): {'有' if current_price > low_est else '无'}安全边际")
            print(f"  相比中值({mid_est:.2f}元): {'有' if current_price > mid_est else '无'}安全边际")
            print(f"  格雷厄姆买入点(中值×0.85): {mid_est*0.85:.2f}元 → 当前价{'高于' if current_price > mid_est*0.85 else '低于'}买入点")
    
    # 保存结果
    output = {
        'stock_code': stock_code,
        'current_price': current_price,
        'key_metrics': {
            'eps': eps,
            'bps': bps,
            'roe': roe,
            'net_cash_ratio': net_cash_ratio
        },
        'valuations': results
    }
    
    output_file = os.path.join(data_dir, f"valuation_multi_{stock_code}.json")
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print(f"\n✅ 估值结果已保存: {output_file}")
    
    return results


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python3 valuation_multi.py <股票代码> [数据目录]")
        sys.exit(1)
    
    code = sys.argv[1]
    data_dir = sys.argv[2] if len(sys.argv) > 2 else "."
    main(code, data_dir)
