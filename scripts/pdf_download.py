#!/usr/bin/env python3
"""
年报PDF下载模块
支持下载：年报、半年报、季报（Q1/Q3）

用法: python3 pdf_download.py <股票代码> <输出目录> [--type annual|half|quarterly|all]
"""

import sys
import os
import json
import time
import requests
from datetime import datetime

# 巨潮资讯PDF直链格式
# http://static.cninfo.com.cn/finalpage/<日期>/<公告ID>.PDF


def get_annual_reports_cninfo(stock_code):
    """
    通过巨潮资讯API获取年报列表
    category: 年报= категория, 半年报=2, 季报=3
    """
    url = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'application/json, text/javascript, */*; q=0.01',
        'Accept-Language': 'zh-CN,zh;q=0.9',
        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
        'Origin': 'http://www.cninfo.com.cn',
        'Referer': 'http://www.cninfo.com.cn/new/disclosure/stock?stockCode={}&orgId={}'
    }
    
    # 尝试多个category
    categories = {
        '年报': '12',
        '半年报': '2', 
        '一季报': '3',
        '三季报': '3',
    }
    
    all_reports = []
    
    for report_type, category in categories.items():
        payload = {
            'stockCode': stock_code,
            'orgId': '',  # orgId可以不填
            'category': category,
            'pageNum': '1',
            'pageSize': '20',
            'tabName': 'fulltext',
            'plate': '',
            'seDate': '',
            'column': '',
            'searchkey': '',
            'secid': '',
            'category': '',
            'trade': '',
        }
        
        try:
            response = requests.post(url, data=payload, headers=headers, timeout=15)
            data = response.json()
            
            if data.get('announcements'):
                for item in data['announcements']:
                    # 过滤年报/半年报/季报关键词
                    title = item.get('announcementTitle', '')
                    if any(kw in title for kw in ['年度报告', '半年度报告', '季度报告', '一季报', '三季报', '半年报']):
                        all_reports.append({
                            'type': '年报' if '年度' in title else ('半年报' if '半年度' in title else '季报'),
                            'title': title,
                            'announcementId': item.get('announcementId'),
                            'publishTime': item.get('publishTime'),
                            'adjunctUrl': item.get('adjunctUrl'),
                            ' adjunctSize': item.get('adjunctSize', 0),
                        })
        except Exception as e:
            print(f"  ⚠️ 获取{report_type}列表失败: {e}")
            continue
        
        time.sleep(0.5)  # 避免请求过快
    
    # 去重（按标题）
    seen = set()
    unique_reports = []
    for r in all_reports:
        if r['title'] not in seen:
            seen.add(r['title'])
            unique_reports.append(r)
    
    return unique_reports


def get_reports_by_akshare(stock_code):
    """
    通过akshare获取年报列表（备选方案）
    """
    try:
        import akshare as ak
        
        # 使用公告接口
        df = ak.stock_zh_a_disclosure_report_cninfo(symbol=stock_code)
        
        reports = []
        for _, row in df.iterrows():
            title = str(row.get('公告标题', ''))
            if any(kw in title for kw in ['年度', '半年', '季度', '一季', '三季']):
                reports.append({
                    'title': title,
                    'announcementId': str(row.get('公告ID', '')),
                    'publishTime': str(row.get('公告时间', '')),
                    'adjunctUrl': str(row.get('附件URL', row.get('adjunctUrl', ''))),
                    'type': '年报' if '年度' in title else ('半年报' if '半年' in title else '季报'),
                })
        
        return reports
    
    except Exception as e:
        print(f"  ⚠️ akshare接口失败: {e}")
        return []


def download_pdf(url, output_path, timeout=30):
    """
    下载PDF文件
    支持直链和cninfo格式
    """
    if not url:
        return False, "URL为空"
    
    # 补全cninfo直链
    if 'static.cninfo.com.cn' not in url and '/finalpage/' not in url:
        # 构造cninfo直链
        if url.startswith('/'):
            url = 'http://static.cninfo.com.cn' + url
        elif not url.startswith('http'):
            url = 'http://static.cninfo.com.cn/finalpage/' + url
    
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'http://www.cninfo.com.cn/',
        }
        
        response = requests.get(url, headers=headers, timeout=timeout, stream=True)
        
        if response.status_code == 200:
            content_type = response.headers.get('Content-Type', '')
            if 'pdf' in content_type.lower() or response.headers.get('Content-Disposition'):
                with open(output_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                size = os.path.getsize(output_path)
                return True, f"下载成功 ({size//1024}KB)"
            elif 'html' in content_type.lower():
                return False, "服务器返回HTML（文件不存在）"
            else:
                # 尝试直接保存
                with open(output_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                size = os.path.getsize(output_path)
                if size > 10000:  # 大于10KB才认为下载成功
                    return True, f"下载成功 ({size//1024}KB)"
                else:
                    os.remove(output_path)
                    return False, f"文件过小({size}字节)，可能是错误页面"
        else:
            return False, f"HTTP {response.status_code}"
    
    except requests.exceptions.Timeout:
        return False, "下载超时"
    except requests.exceptions.ConnectionError:
        return False, "连接失败"
    except Exception as e:
        return False, str(e)


def build_cninfo_direct_url(adjunct_url):
    """
    从cninfo附件URL构建直链
    cninfo附件URL格式: /new/announcement/detail?announceTime=XXX&announcementId=XXX
    直链格式: http://static.cninfo.com.cn/finalpage/<日期>/<ID>.PDF
    """
    if not adjunct_url:
        return None
    
    # 如果已经是直链格式
    if 'static.cninfo.com.cn' in adjunct_url:
        return adjunct_url
    
    # 已经是完整PDF链接
    if '.PDF' in adjunct_url.upper() or '.pdf' in adjunct_url.lower():
        return adjunct_url
    
    # 尝试从announcementId构造
    # 公告ID通常是数字，直接用于直链
    # 有些年份的PDF存储在带日期的目录
    # 格式: http://static.cninfo.com.cn/finalpage/<YYMMDD>/<ID>.PDF
    return None  # 返回None，让调用方使用备用方案


def try_download_with_curl(pdf_url, output_path):
    """用curl下载（备选方案）"""
    import subprocess
    
    try:
        result = subprocess.run(
            ['curl', '-s', '-L', '-o', output_path, 
             '-H', 'User-Agent: Mozilla/5.0',
             '-H', 'Referer: http://www.cninfo.com.cn/',
             pdf_url],
            capture_output=True, text=True, timeout=30
        )
        
        if result.returncode == 0 and os.path.exists(output_path):
            size = os.path.getsize(output_path)
            if size > 10000:
                return True, f"curl下载成功 ({size//1024}KB)"
        
        return False, "curl下载失败"
    
    except FileNotFoundError:
        return False, "curl未安装"


def main(stock_code, output_dir=".", report_type="all"):
    print(f"\n{'='*60}")
    print(f"年报PDF下载 — {stock_code}")
    print(f"{'='*60}\n")
    
    os.makedirs(output_dir, exist_ok=True)
    
    # 确定要下载的报告类型
    if report_type == "all":
        types_to_download = ['年报', '半年报', '季报']
    else:
        types_to_download = [report_type]
    
    all_reports = []
    
    # 方法1：通过cninfo API
    print("📡 尝试方法1: 巨潮资讯API...")
    cninfo_reports = get_annual_reports_cninfo(stock_code)
    
    if cninfo_reports:
        print(f"  获取到 {len(cninfo_reports)} 条公告")
        all_reports.extend(cninfo_reports)
    else:
        print("  ⚠️ 巨潮API未返回数据")
    
    # 方法2：通过akshare（备选）
    if not all_reports:
        print("\n📡 尝试方法2: akshare接口...")
        akshare_reports = get_reports_by_akshare(stock_code)
        if akshare_reports:
            print(f"  获取到 {len(akshare_reports)} 条公告")
            all_reports.extend(akshare_reports)
    
    if not all_reports:
        print("❌ 无法获取报告列表，尝试直接构造年报URL...")
        # 直接尝试已知的年报公告ID格式
        # 永新股份2024年报: announcementId=1219663495
        # 这个方法需要具体股票具体分析，保留一个备用方案
        print("⚠️ 请手动从巨潮网站获取年报PDF链接")
        print("   网址: http://www.cninfo.com.cn/new/disclosure/stock?stockCode=" + stock_code)
        return
    
    # 去重
    seen_ids = set()
    unique_reports = []
    for r in all_reports:
        if r.get('announcementId') and r['announcementId'] not in seen_ids:
            seen_ids.add(r['announcementId'])
            unique_reports.append(r)
    
    # 按时间排序（最新优先）
    unique_reports.sort(key=lambda x: x.get('publishTime', ''), reverse=True)
    
    print(f"\n📋 待下载报告列表（共{len(unique_reports)}份）:")
    for r in unique_reports:
        time_str = r.get('publishTime', '未知时间')
        if isinstance(time_str, (int, float)):
            from datetime import datetime
            time_str = datetime.fromtimestamp(time_str/1000).strftime('%Y-%m-%d')
        print(f"  [{r.get('type','?')}] {time_str} | {r.get('title','无标题')}")
    
    # 下载报告
    print(f"\n📥 开始下载到: {output_dir}")
    print("-" * 60)
    
    downloaded = []
    failed = []
    
    for i, report in enumerate(unique_reports):
        title = report.get('title', '未知')
        report_type_label = report.get('type', '未知')
        adjunct_url = report.get('adjunctUrl', '')
        ann_id = report.get('announcementId', '')
        
        # 构造输出文件名
        time_str = report.get('publishTime', 'nodate')
        if isinstance(time_str, str) and len(time_str) >= 10:
            date_str = time_str[:10].replace('-', '')
        else:
            date_str = 'nodate'
        
        safe_title = ''.join(c for c in title[:20] if c not in '/\\:*?"<>|')
        filename = f"{report_type_label}_{date_str}_{safe_title}.pdf"
        output_path = os.path.join(output_dir, filename)
        
        print(f"\n[{i+1}/{len(unique_reports)}] {report_type_label} | {title}")
        
        # 尝试多种URL格式
        download_url = None
        urls_to_try = []
        
        if adjunct_url:
            urls_to_try.append(adjunct_url)
            # 尝试构造直链
            if ann_id:
                # 有些PDF直接以announcementId为文件名
                urls_to_try.append(f"http://static.cninfo.com.cn/finalpage/{ann_id}.PDF")
                # 带日期格式
                urls_to_try.append(f"http://static.cninfo.com.cn/finalpage/{date_str}/{ann_id}.PDF")
        
        for url in urls_to_try:
            if not url:
                continue
            success, msg = download_pdf(url, output_path)
            if success:
                download_url = url
                print(f"  ✅ {msg}")
                downloaded.append({
                    'report': report,
                    'path': output_path,
                    'url': download_url
                })
                break
            else:
                print(f"  ⚠️ {url[:60]}... → {msg}")
        
        if not download_url:
            # 尝试curl作为最后手段
            for url in urls_to_try:
                if url:
                    success, msg = try_download_with_curl(url, output_path)
                    if success:
                        download_url = url
                        print(f"  ✅ curl备用: {msg}")
                        downloaded.append({
                            'report': report,
                            'path': output_path,
                            'url': download_url
                        })
                        break
        
        if not download_url:
            print(f"  ❌ 下载失败")
            failed.append(report)
        
        time.sleep(0.3)  # 避免过快
    
    # 结果汇总
    print("\n" + "=" * 60)
    print("下载结果汇总")
    print("=" * 60)
    print(f"✅ 成功: {len(downloaded)} 份")
    print(f"❌ 失败: {len(failed)} 份")
    
    if downloaded:
        print(f"\n📁 已下载文件:")
        for d in downloaded:
            print(f"  {d['path']}")
    
    if failed:
        print(f"\n⚠️ 未下载（可手动获取）:")
        for f in failed:
            print(f"  {f.get('type','?')} | {f.get('title','无标题')}")
            print(f"    URL: {f.get('adjunctUrl','')}")
    
    # 保存下载记录
    log_path = os.path.join(output_dir, f"download_log_{stock_code}.json")
    log = {
        'stock_code': stock_code,
        'download_time': datetime.now().isoformat(),
        'downloaded': downloaded,
        'failed': failed,
    }
    with open(log_path, 'w', encoding='utf-8') as f:
        json.dump(log, f, ensure_ascii=False, indent=2)
    
    print(f"\n📋 下载记录已保存: {log_path}")
    return downloaded, failed


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python3 pdf_download.py <股票代码> <输出目录> [--type annual|half|quarterly|all]")
        print("\n示例:")
        print("  python3 pdf_download.py 002014 ./reports")
        print("  python3 pdf_download.py 002014 ./reports --type annual")
        sys.exit(1)
    
    code = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else "."
    report_type = "all"
    
    if len(sys.argv) > 3 and sys.argv[3] == '--type':
        report_type = sys.argv[4] if len(sys.argv) > 4 else "all"
    
    main(code, output_dir, report_type)
