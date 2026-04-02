#!/usr/bin/env python3
"""
年报PDF下载脚本
用法: python3 pdf_download.py <股票代码> <报告年份> <公告ID> <输出文件>
例如: python3 pdf_download.py 002014 2024 1219663495 ./annual_report_2024.pdf

公告ID获取方式：
1. 巨潮资讯网页: http://www.cninfo.com.cn -> 搜索股票 -> 年报公告
2. akshare: ak.stock_zh_a_disclosure_report_cninfo(symbol, start_date, end_date)
   注意: akshare的cninfo接口有时报brotli错误, 此时直接用curl
"""
import requests
import sys
import os
import time

def download_pdf(stock_code, year, announcement_id, output_file):
    # 巨潮PDF直链格式
    base_url = "http://static.cninfo.com.cn/finalpage"
    # 格式1: /YYYY-MM-DD/<ID>.PDF
    # 格式2: 直接用ID
    
    urls_to_try = [
        f"http://static.cninfo.com.cn/finalpage/{year}-04-{announcement_id}.PDF",
        f"http://static.cninfo.com.cn/finalpage/{announcement_id}.PDF",
    ]
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'application/pdf,*/*',
        'Referer': 'http://www.cninfo.com.cn/',
    }
    
    for url in urls_to_try:
        print(f"尝试: {url}")
        try:
            r = requests.get(url, headers=headers, timeout=30, allow_redirects=True)
            if r.status_code == 200 and len(r.content) > 10000:
                os.makedirs(os.path.dirname(output_file) or '.', exist_ok=True)
                with open(output_file, 'wb') as f:
                    f.write(r.content)
                print(f"✅ 下载成功: {output_file} ({len(r.content)/1024:.0f}KB)")
                return True
            else:
                print(f"  响应: {r.status_code}, 大小: {len(r.content)}")
        except Exception as e:
            print(f"  错误: {e}")
        time.sleep(0.5)
    
    print("❌ 所有URL均失败")
    print(f"\n手动下载方法:")
    print(f"  1. 打开 http://www.cninfo.com.cn")
    print(f"  2. 搜索股票 {stock_code}")
    print(f"  3. 找到 {year} 年报公告")
    print(f"  4. 下载PDF到: {output_file}")
    return False

if __name__ == '__main__':
    if len(sys.argv) < 5:
        print(__doc__)
        sys.exit(1)
    download_pdf(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4])
