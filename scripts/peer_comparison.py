#!/usr/bin/env python3
"""
同业比较模块
自动选取可比公司，计算行业百分位排名

用法: python3 peer_comparison.py <股票代码> [数据目录]
"""

import sys
import os
import json
import math
import pandas as pd


def get_industry_peers(stock_code):
    """
    获取同业公司列表
    使用akshare行业分类接口
    """
    try:
        import akshare as ak
        
        # 获取所有行业板块
        industries = ak.stock_board_industry_name_em()
        print(f"找到 {len(industries)} 个行业板块")
        
        # 获取成分股
        all_peers = []
        for _, row in industries.iterrows():
            industry_name = row.get('板块名称', '')
            try:
                cons = ak.stock_board_industry_cons_em(symbol=industry_name)
                if '代码' in cons.columns and len(cons) > 0:
                    codes = cons['代码'].tolist()
                    all_peers.extend([(code, industry_name) for code in codes])
            except Exception:
                continue
        
        return all_peers  # [(code, industry_name), ...]
    
    except Exception as e:
        print(f"⚠️ 无法获取行业数据: {e}")
        return []


def get_stock_basic_info(stock_code):
    """获取股票基本信息（名称、行业、市值等）"""
    try:
        import akshare as ak
        df = ak.stock_individual_info_em(symbol=stock_code)
        info = {}
        for _, row in df.iterrows():
            info[row.get('item', '')] = row.get('value', '')
        return info
    except Exception:
        return {}


def get_financial_metrics(stock_code, years=3):
    """
    获取个股财务指标
    返回关键指标字典
    """
    try:
        import akshare as ak
        
        metrics = {'code': stock_code}
        
        # 综合财务指标
        df = ak.stock_financial_analysis_indicator(symbol=stock_code, start_year='2022')
        
        if df is not None and len(df) > 0:
            df['日期_str'] = df['日期'].astype(str)
            df = df.sort_values('日期', ascending=False)
            latest = df.iloc[0]
            
            metrics['eps'] = float(latest.get('摊薄每股收益', 0) or 0)
            metrics['bps'] = float(latest.get('每股净资产', 0) or 0)
            metrics['roe'] = float(latest.get('净资产收益率(%)', 0) or 0)
            metrics['net_margin'] = float(latest.get('销售净利率', 0) or 0)
            metrics['gross_margin'] = float(latest.get('销售毛利率', 0) or 0)
            metrics['debt_ratio'] = float(latest.get('资产负债率', 0) or 0)
            metrics['pe_ttm'] = float(latest.get('市盈率(TTM)', 0) or 0)
            metrics['pb'] = float(latest.get('市净率', 0) or 0)
            metrics['total_asset_turnover'] = float(latest.get('总资产周转率(次)', 0) or 0)
            
            # 3年年报数据（计算增速）
            if len(df) >= 2:
                y1 = df.iloc[0]
                y2 = df.iloc[min(1, len(df)-1)]
                
                rev_growth = safe_div(
                    float(y1.get('营业总收入', 0) or 0) - float(y2.get('营业总收入', 0) or 0),
                    abs(float(y2.get('营业总收入', 0) or 0))
                )
                metrics['revenue_growth'] = rev_growth
                
                profit_growth = safe_div(
                    float(y1.get('净利润', 0) or 0) - float(y2.get('净利润', 0) or 0),
                    abs(float(y2.get('净利润', 0) or 0))
                )
                metrics['profit_growth'] = profit_growth
            
            # 现金流
            try:
                cf_df = ak.stock_cashflow_spot_em(symbol=stock_code)
                if cf_df is not None and len(cf_df) > 0:
                    latest_cf = cf_df.sort_values('日期', ascending=False).iloc[0]
                    operating_cf = float(latest_cf.get('经营活动产生的现金流量净额', 0) or 0)
                    net_profit = float(latest_cf.get('净利润', 0) or 0)
                    metrics['net_cash_ratio'] = safe_div(operating_cf, net_profit)
            except Exception:
                metrics['net_cash_ratio'] = None
        
        return metrics
    
    except Exception as e:
        print(f"⚠️ 获取{stock_code}财务数据失败: {e}")
        return {'code': stock_code, 'error': str(e)}


def safe_div(a, b, default=None):
    try:
        return a / b if b and b != 0 else default
    except (TypeError, ValueError):
        return default


def percentile_rank(value, all_values, reverse=False):
    """
    计算百分位排名
    reverse=True: 值越小越好（如PE、资产负债率）
    reverse=False: 值越大越好（如ROE、净利率）
    """
    if value is None or math.isnan(value if isinstance(value, float) else 0):
        return None
    
    valid = [v for v in all_values if v is not None and not math.isnan(v if isinstance(v, float) else 0)]
    if not valid:
        return None
    
    count = sum(1 for v in valid if (v < value if reverse else v > value))
    return (count / len(valid)) * 100


def score_peer(metrics, weights):
    """
    计算同业比较综合得分
    weights: 各维度权重
    """
    score = 0
    total_weight = 0
    
    # ROE（盈利能力）
    if metrics.get('roe') is not None:
        score += metrics['roe'] * weights.get('roe', 0.15)
        total_weight += weights.get('roe', 0.15)
    
    # 净利率
    if metrics.get('net_margin') is not None:
        score += metrics['net_margin'] * 100 * weights.get('net_margin', 0.10)
        total_weight += weights.get('net_margin', 0.10)
    
    # 毛利率
    if metrics.get('gross_margin') is not None:
        score += metrics['gross_margin'] * 100 * weights.get('gross_margin', 0.05)
        total_weight += weights.get('gross_margin', 0.05)
    
    # 营收增速
    if metrics.get('revenue_growth') is not None:
        # 增速给分，0%=0分，20%+=10分
        growth_score = min(metrics['revenue_growth'] * 50, 10)
        score += growth_score * weights.get('revenue_growth', 0.10)
        total_weight += weights.get('revenue_growth', 0.10)
    
    # PE（估值，越低越好）
    if metrics.get('pe_ttm') and metrics['pe_ttm'] > 0:
        # PE=10倍=10分，PE=30倍=0分
        pe_score = max(10 - (metrics['pe_ttm'] - 10) * 0.5, 0)
        score += pe_score * weights.get('pe', 0.15)
        total_weight += weights.get('pe', 0.15)
    
    # PB（估值，越低越好）
    if metrics.get('pb') and metrics['pb'] > 0:
        # PB=1=10分，PB=5=0分
        pb_score = max(10 - (metrics['pb'] - 1) * 2.5, 0)
        score += pb_score * weights.get('pb', 0.10)
        total_weight += weights.get('pb', 0.10)
    
    # 净现比
    if metrics.get('net_cash_ratio') is not None:
        # 1.0=10分，0.5=0分
        cf_score = max((metrics['net_cash_ratio'] - 0.5) * 20, 0)
        score += cf_score * weights.get('net_cash_ratio', 0.10)
        total_weight += weights.get('net_cash_ratio', 0.10)
    
    # 资产负债率（越低越好）
    if metrics.get('debt_ratio') is not None:
        # 20%=10分，60%=0分
        debt_score = max(10 - (metrics['debt_ratio'] - 0.20) * 25, 0)
        score += debt_score * weights.get('debt_ratio', 0.10)
        total_weight += weights.get('debt_ratio', 0.10)
    
    # 总资产周转率
    if metrics.get('total_asset_turnover') is not None:
        # 1.0次=5分，上下浮动
        turnover_score = metrics['total_asset_turnover'] * 5
        score += turnover_score * weights.get('turnover', 0.05)
        total_weight += weights.get('turnover', 0.05)
    
    return safe_div(score, total_weight) * 10 if total_weight > 0 else None


def main(stock_code, data_dir=".", max_peers=10):
    print(f"\n{'='*60}")
    print(f"同业比较分析 — {stock_code}")
    print(f"{'='*60}\n")
    
    # 获取目标股票信息
    target_info = get_stock_basic_info(stock_code)
    target_name = target_info.get('股票名称', stock_code)
    target_industry = target_info.get('行业', '未知')
    print(f"目标股票: {target_name}（{stock_code}）")
    print(f"行业: {target_industry}")
    print()
    
    # 获取同业公司
    print("正在获取同业公司列表...")
    all_peers = get_industry_peers(stock_code)
    
    # 筛选同行（同一行业）
    target_in_peers = [p for p in all_peers if p[0] == stock_code]
    
    # 简单方案：如果无法确定行业，找同概念板块的公司
    peer_codes = []
    if target_in_peers:
        industry_name = target_in_peers[0][1]
        peer_codes = [p[0] for p in all_peers if p[1] == industry_name and p[0] != stock_code]
    else:
        # 备选：用市值相近的非ST股票作为泛可比集
        print("⚠️ 无法确定精确行业，使用备选方案")
        peer_codes = []
    
    # 如果同行太少（<5家），加入一些主要同行
    if len(peer_codes) < 5:
        # 保留现有的，找不到更多同行时用行业ETF成分股替代
        print(f"⚠️ 同行公司数量不足({len(peer_codes)})，结果仅供参考")
    
    # 限制最多比较公司数量
    peer_codes = peer_codes[:max_peers * 3]  # 留足筛选余地
    
    print(f"初步筛选: {len(peer_codes)} 家同业候选")
    
    # 获取同业财务数据
    print("正在获取同业财务数据（这可能需要几分钟）...")
    peer_metrics = []
    
    for i, peer_code in enumerate(peer_codes):
        if (i + 1) % 20 == 0:
            print(f"  已处理 {i+1}/{len(peer_codes)} ...")
        
        try:
            m = get_financial_metrics(peer_code)
            if m and 'error' not in m and m.get('roe') is not None and m.get('roe', 0) > 0:
                peer_metrics.append(m)
        except Exception:
            continue
    
    print(f"获取到 {len(peer_metrics)} 家公司的有效数据")
    
    if not peer_metrics:
        print("❌ 无法获取足够的同业数据，同业比较失败")
        return
    
    # 加入目标股票
    target_metrics = get_financial_metrics(stock_code)
    if target_metrics and 'error' not in target_metrics:
        peer_metrics.append(target_metrics)
    
    # 提取各维度数据用于百分位计算
    roe_vals = [m.get('roe') for m in peer_metrics if m.get('roe') is not None]
    pe_vals = [m.get('pe_ttm') for m in peer_metrics if m.get('pe_ttm') and m['pe_ttm'] > 0]
    pb_vals = [m.get('pb') for m in peer_metrics if m.get('pb') and m['pb'] > 0]
    nm_vals = [m.get('net_margin') * 100 for m in peer_metrics if m.get('net_margin') is not None]
    gm_vals = [m.get('gross_margin') * 100 for m in peer_metrics if m.get('gross_margin') is not None]
    cf_vals = [m.get('net_cash_ratio') for m in peer_metrics if m.get('net_cash_ratio') is not None]
    debt_vals = [m.get('debt_ratio') * 100 for m in peer_metrics if m.get('debt_ratio') is not None]
    rev_g_vals = [m.get('revenue_growth') * 100 for m in peer_metrics if m.get('revenue_growth') is not None]
    turn_vals = [m.get('total_asset_turnover') for m in peer_metrics if m.get('total_asset_turnover') is not None]
    
    # 计算百分位
    for m in peer_metrics:
        m['roe_pct'] = percentile_rank(m.get('roe'), roe_vals)
        m['pe_pct'] = percentile_rank(m.get('pe_ttm'), pe_vals, reverse=True)  # PE越低越好
        m['pb_pct'] = percentile_rank(m.get('pb'), pb_vals, reverse=True)  # PB越低越好
        m['nm_pct'] = percentile_rank(m.get('net_margin') * 100 if m.get('net_margin') else None, nm_vals)
        m['gm_pct'] = percentile_rank(m.get('gross_margin') * 100 if m.get('gross_margin') else None, gm_vals)
        m['cf_pct'] = percentile_rank(m.get('net_cash_ratio'), cf_vals)
        m['debt_pct'] = percentile_rank(m.get('debt_ratio') * 100 if m.get('debt_ratio') else None, debt_vals, reverse=True)  # 负债越低越好
        m['rev_g_pct'] = percentile_rank(m.get('revenue_growth') * 100 if m.get('revenue_growth') else None, rev_g_vals)
        
        # 综合得分
        weights = {
            'roe': 0.20, 'net_margin': 0.10, 'gross_margin': 0.05,
            'revenue_growth': 0.10, 'pe': 0.15, 'pb': 0.10,
            'net_cash_ratio': 0.15, 'debt_ratio': 0.10, 'turnover': 0.05
        }
        m['composite_score'] = score_peer(m, weights)
    
    # 按综合得分排序
    peer_metrics.sort(key=lambda x: x.get('composite_score') or 0, reverse=True)
    
    # 找出目标股票排名
    target_rank = None
    for i, m in enumerate(peer_metrics):
        if m['code'] == stock_code:
            target_rank = i + 1
            break
    
    # 输出结果
    print(f"\n{'='*70}")
    print(f"同业比较结果（共{len(peer_metrics)}家可比公司）")
    print(f"{'='*70}\n")
    
    header = f"{'代码':<8} {'ROE':>6} {'PE':>6} {'PB':>5} {'净利率':>6} {'净现比':>6} {'资产负债':>7} {'综合得分':>8} {'行业位置':>8}"
    print(header)
    print("-" * 70)
    
    for rank, m in enumerate(peer_metrics, 1):
        code = m['code']
        marker = " ← " if code == stock_code else "    "
        rank_str = f"第{rank}/{len(peer_metrics)}" if code == stock_code else ""
        
        print(
            f"{code:<8}"
            f"{m.get('roe', 0):>6.1f}%"
            f"{m.get('pe_ttm', 0):>6.1f}"
            f"{m.get('pb', 0):>5.2f}"
            f"{(m.get('net_margin') or 0)*100:>6.1f}%"
            f"{m.get('net_cash_ratio') or 0:>6.2f}"
            f"{(m.get('debt_ratio') or 0)*100:>7.1f}%"
            f"{m.get('composite_score') or 0:>8.1f}"
            f"{marker}{code if code == stock_code else ''}{rank_str}"
        )
    
    print("-" * 70)
    
    if target_rank:
        print(f"\n📊 {target_name}（{stock_code}）在同业中排名：第{target_rank}/{len(peer_metrics)}位（前{round((1-target_rank/len(peer_metrics))*100,1)}%）")
        
        # 关键指标亮点
        tm = next((m for m in peer_metrics if m['code'] == stock_code), {})
        
        print("\n关键指标表现:")
        indicators = [
            ('roe', 'ROE', True),
            ('pe_ttm', 'PE', False),
            ('pb', 'PB', False),
            ('net_margin', '净利率', True),
            ('net_cash_ratio', '净现比', True),
            ('debt_ratio', '资产负债率', False),
        ]
        
        for key, name, higher_better in indicators:
            val = tm.get(key)
            pct = tm.get(f'{key}_pct'.replace('_ttm',''))
            
            if val is None:
                continue
            
            if key == 'debt_ratio':
                val_str = f"{val*100:.1f}%"
            elif key in ('roe', 'net_margin'):
                val_str = f"{val*100:.1f}%"
            elif key == 'net_cash_ratio':
                val_str = f"{val:.2f}"
            else:
                val_str = f"{val:.2f}"
            
            if pct is not None:
                position = "⭐优秀" if pct >= 75 else ("⚠️偏差" if pct <= 25 else "中等")
                print(f"  {name}: {val_str} → 行业前{int(pct)}% {position}")
            else:
                print(f"  {name}: {val_str}")
    
    # 保存结果
    output = {
        'target_code': stock_code,
        'target_name': target_name,
        'industry': target_industry,
        'total_peers': len(peer_metrics),
        'target_rank': target_rank,
        'peer_metrics': peer_metrics
    }
    
    output_file = os.path.join(data_dir, f"peer_comparison_{stock_code}.json")
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print(f"\n✅ 同业比较结果已保存: {output_file}")
    return peer_metrics


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python3 peer_comparison.py <股票代码> [数据目录]")
        sys.exit(1)
    
    code = sys.argv[1]
    data_dir = sys.argv[2] if len(sys.argv) > 2 else "."
    main(code, data_dir)
