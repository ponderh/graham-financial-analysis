#!/usr/bin/env python3
"""
格雷厄姆财务分析 - 核心指标计算脚本
用法: python3 analyze_modules.py <股票代码> <数据目录>
"""
import pandas as pd
import numpy as np
import sys
import math

def analyze(stock_code, data_dir):
    print(f"📈 计算 {stock_code} 核心指标...")

    # 读取年报数据
    df = pd.read_csv(f'{data_dir}/financial_indicator_annual.csv')
    df['日期'] = df['日期'].astype(str)

    print("\n=== 关键财务数据 (最近3年) ===")
    key_cols = ['日期', '摊薄每股收益(元)', '加权每股收益(元)', '每股净资产_调整前(元)',
                '净资产收益率(%)', '加权净资产收益率(%)', '销售净利率(%)',
                '销售毛利率(%)', '资产负债率(%)', '总资产(元)',
                '流动比率', '速动比率', '总资产周转率(次)', 
                '存货周转天数(天)', '应收账款周转天数(天)']
    
    available = [c for c in key_cols if c in df.columns]
    print(df[available].to_string(index=False))

    # === 格雷厄姆数计算 ===
    latest = df.iloc[-1]
    eps = latest['加权每股收益(元)'] if '加权每股收益(元)' in latest else latest.get('摊薄每股收益(元)', 0)
    bps = latest.get('每股净资产_调整前(元)', 0)
    roe = latest.get('加权净资产收益率(%)', 0)

    print(f"\n=== 格雷厄姆数计算 ===")
    print(f"EPS(加权): {eps:.4f}")
    print(f"BPS: {bps:.4f}")
    print(f"ROE: {roe:.2f}%")

    # 保守版
    graham_conservative = math.sqrt(22.5 * eps * bps)
    print(f"格雷厄姆数(保守版) = √(22.5 × {eps:.4f} × {bps:.4f}) = {graham_conservative:.2f}元")

    # 成长调整版
    rf = 3.0  # 无风险利率
    g = 5.0   # 永续增长率
    if roe > 15:
        factor = 1 + 0.5 * (roe - rf) / 100
        graham_growth = math.sqrt(22.5 * eps * bps * factor)
        print(f"格雷厄姆数(成长调整版) = √(22.5 × {eps:.4f} × {bps:.4f} × {factor:.4f}) = {graham_growth:.2f}元")
        print(f"  (ROE={roe:.2f}%>{rf:.1f}%, 使用成长调整因子={factor:.4f})")
    else:
        print(f"  ROE={roe:.2f}%<=15%, 不适用成长调整")

    # === 净现比计算 ===
    print(f"\n=== 净现比趋势 ===")
    cf_cols = [c for c in df.columns if '每股经营性现金流(元)' in c or '每股经营现金流' in c]
    if cf_cols:
        for _, row in df.iterrows():
            eps_val = row.get('摊薄每股收益(元)', 0)
            op_cf = row.get(cf_cols[0], 0)
            if pd.notna(eps_val) and pd.notna(op_cf) and eps_val > 0:
                ratio = op_cf / eps_val
                print(f"  {row['日期']}: 经营CF={op_cf:.4f}, EPS={eps_val:.4f}, 净现比={ratio:.2f}")

    # === 毛利率稳定性 ===
    print(f"\n=== 毛利率稳定性 ===")
    if '销售毛利率(%)' in df.columns:
        margins = df['销售毛利率(%)'].dropna()
        if len(margins) >= 2:
            cv = margins.std() / margins.mean() * 100
            print(f"  3年毛利率: {margins.tolist()}")
            print(f"  变异系数CV={cv:.2f}% (CV<15%为稳定, CV>20%为不稳定)")

    # === 上下游占款能力 ===
    print(f"\n=== 上下游占款能力 ===")
    # 需要从资产负债表中计算
    # (应付+预收-应收-预付)/营收
    # 参考数据：df['应付票据及应付账款(元)'], df['预收款项(元)'] 等
    
    print("  注：需读取balance_sheet.csv进行详细计算")
    print("  公式：(应付+预收-应收-预付)/营业收入")

    print(f"\n=== 分析完成 ===")

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("用法: python3 analyze_modules.py <股票代码> <数据目录>")
        sys.exit(1)
    analyze(sys.argv[1], sys.argv[2])
