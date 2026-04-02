#!/usr/bin/env python3
"""
格雷厄姆财务分析 - 数据采集脚本
用法: python3 data_fetch.py <股票代码> <输出目录>
例如: python3 data_fetch.py 002014 ./analysis
"""
import akshare as ak
import pandas as pd
import sys
import os
import time

def fetch_all(stock_code, output_dir):
    os.makedirs(output_dir, exist_ok=True)
    
    print(f"📊 采集 {stock_code} 财务数据...")

    # 1. 综合财务指标（86+字段）
    print("  [1/6] 综合财务指标...")
    df = ak.stock_financial_analysis_indicator(symbol=stock_code, start_year='2022')
    df['日期_str'] = df['日期'].astype(str)
    annual = df[df['日期_str'].str.contains('12-31')].sort_values('日期_str')
    annual.drop(columns=['日期_str']).to_csv(
        f'{output_dir}/financial_indicator_annual.csv', index=False, encoding='utf-8-sig')
    print(f"  ✅ 综合指标: {len(annual)}年年报, 年份: {annual['日期_str'].tolist()}")

    time.sleep(1)

    # 2. 利润表
    print("  [2/6] 利润表...")
    prof = ak.stock_profit_sheet_by_report_em(symbol=stock_code)
    prof.to_csv(f'{output_dir}/profit_sheet.csv', index=False, encoding='utf-8-sig')
    print(f"  ✅ 利润表: {prof.shape}")

    time.sleep(1)

    # 3. 资产负债表
    print("  [3/6] 资产负债表...")
    bal = ak.stock_balance_sheet_by_report_em(symbol=stock_code)
    bal.to_csv(f'{output_dir}/balance_sheet.csv', index=False, encoding='utf-8-sig')
    print(f"  ✅ 资产负债表: {bal.shape}")

    time.sleep(1)

    # 4. 现金流量表
    print("  [4/6] 现金流量表...")
    cf = ak.stock_cash_flow_sheet_by_report_em(symbol=stock_code)
    cf.to_csv(f'{output_dir}/cashflow_sheet.csv', index=False, encoding='utf-8-sig')
    print(f"  ✅ 现金流量表: {cf.shape}")

    time.sleep(1)

    # 5. 公司信息
    print("  [5/6] 公司信息...")
    info = ak.stock_individual_info_em(symbol=stock_code)
    info.to_csv(f'{output_dir}/company_info.csv', index=False, encoding='utf-8-sig')
    print(f"  ✅ 公司信息: {info.shape}")

    time.sleep(1)

    # 6. 股价历史（前复权）
    print("  [6/6] 股价历史...")
    price = ak.stock_zh_a_hist(symbol=stock_code, start_date='20220101', 
                                end_date='20251231', adjust='qfq')
    price.to_csv(f'{output_dir}/price_history.csv', index=False, encoding='utf-8-sig')
    print(f"  ✅ 股价历史: {len(price)} rows")

    print(f"\n✅ 数据采集完成！文件保存在: {output_dir}/")

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    fetch_all(sys.argv[1], sys.argv[2])
