#!/usr/bin/env python3
"""
交易所财报PDF获取与解析模块

功能：
1. 直接对接上交所/深交所API获取财报公告列表
2. 下载年报/半年报/季报PDF
3. 用pdfplumber解析PDF，提取：
   - 财务报表（利润表、资产负债表、现金流量表）
   - 财务报表附注（重要！）
   - 董事会报告
   - 分季度数据

用法:
  python3 exchange_report_fetcher.py <股票代码> <输出目录> [--type annual|half|quarterly|all]
  python3 exchange_report_fetcher.py 688351 ./reports --type annual
"""

import sys
import os
import json
import re
import time
import requests
import pdfplumber
from datetime import datetime, timedelta


# ─────────────────────────────────────────
# 交易所API对接
# ─────────────────────────────────────────

def is_kechuang_board(code):
    """判断是否为科创板股票（上交所）"""
    return code.startswith('688') or code.startswith('787')


def is_shenzhen(code):
    """判断是否为深交所股票"""
    return code.startswith(('000', '001', '002', '003', '300', '301'))


def fetch_sse_reports(stock_code, report_type='all', page=1, page_size=20):
    """
    获取上交所财报公告列表
    包括：年报、半年报、季报
    """
    # 上交所年报公告类型目录ID
    # categoryId: 年报=102001, 半年报=102002, 季报=102003
    
    if report_type == 'annual':
        category_id = '102001'
    elif report_type == 'half':
        category_id = '102002'
    elif report_type == 'quarterly':
        category_id = '102003'
    else:
        category_id = ''  # 所有类型
    
    # 上交所公告查询API
    url = "http://query.sse.com.cn/listedinfo/announcement.do"
    
    params = {
        'jsonCallBack': 'jsonpCallback',
        'action': 'announcement',
        'isPagination': 'true',
        'pageHelp.pageSize': str(page_size),
        'pageHelp.pageNo': str(page),
        'pageHelp.beginDate': '2000-01-01',
        'pageHelp.endDate': datetime.now().strftime('%Y-%m-%d'),
        'stockCode': stock_code,
        'categoryId': category_id,
        'trade': '',
        'seDate': '',
    }
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': 'http://www.sse.com.cn/',
        'Accept': '*/*',
    }
    
    try:
        response = requests.get(url, params=params, headers=headers, timeout=20)
        text = response.text
        
        # 解析JSONP回调
        if text.startswith('jsonpCallback('):
            text = text[len('jsonpCallback('):-1]
        
        data = json.loads(text)
        announcements = data.get('result', [])

        reports = []
        for ann in announcements:
            title = ann.get('TITLE', '')
            # 过滤年报/半年报/季报
            keywords = ['年度报告', '半年度报告', '季度报告', '第一季度报告', '第三季度报告']
            if not any(kw in title for kw in keywords):
                continue
            
            # 构造PDF直链
            pdf_url = None
            for suffix in ['PDF', 'pdf', 'Pdf']:
                url_path = ann.get(f'ATTACHMENT_{suffix}') or ann.get(f'attachment_{suffix}')
                if url_path:
                    pdf_url = f"http://www.sse.com.cn{url_path}" if not url_path.startswith('http') else url_path
                    break
            
            # 备选：从announcementPath构造
            if not pdf_url:
                ann_path = ann.get('announcementPath', '')
                ann_id = ann.get('announcementId', '')
                if ann_id:
                    pdf_url = f"http://www.sse.com.cn/disclosure/listedinfo/announcement/c/{ann_id}.pdf"
            
            # 发布时间
            publish_date = ann.get('PUBLISH_DATE', '')
            if isinstance(publish_date, int):
                publish_date = datetime.fromtimestamp(publish_date/1000).strftime('%Y-%m-%d')
            
            reports.append({
                'title': title,
                'announcementId': ann.get('announcementId', ''),
                'publishDate': publish_date,
                'pdfUrl': pdf_url,
                'category': '年报' if '年度' in title else ('半年报' if '半年度' in title else '季报'),
                'exchange': 'SSE',
                'stockCode': stock_code,
            })
        
        return reports
    
    except Exception as e:
        print(f"  ⚠️ SSE API请求失败: {e}")
        return []


def fetch_szse_reports(stock_code, report_type='all'):
    """
    获取深交所财报公告列表
    """
    # 深交所公告API
    # CATALOGID: 年报=1815, 半年报=1816, 季报=1817
    
    if report_type == 'annual':
        catalog_id = '1815'
    elif report_type == 'half':
        catalog_id = '1816'
    elif report_type == 'quarterly':
        catalog_id = '1817'
    else:
        catalog_id = ''  # 所有类型
    
    url = "http://www.szse.cn/api/report/ShowReport/data"
    
    params = {
        'SHOWTYPE': 'JSON',
        'CATALOGID': catalog_id if catalog_id else '1815',
        'TABKEY': 'tab1',
        'txtStockCode': stock_code,
        'txtQueryDate': datetime.now().strftime('%Y-%m-%d'),
        'random': str(time.time()),
    }
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': 'http://www.szse.cn/',
        'Accept': 'application/json',
    }
    
    try:
        response = requests.get(url, params=params, headers=headers, timeout=20)
        data = response.json()
        
        reports = []
        for item in data:
            records = item.get('data', []) if isinstance(item, dict) else []
            for rec in records:
                title = rec.get('公告标题', '')
                if not title:
                    continue
                
                # 过滤
                keywords = ['年度报告', '半年度报告', '季度报告', '第一季度报告', '第三季度报告']
                if not any(kw in title for kw in keywords):
                    continue
                
                # 构造PDF链接
                pdf_url = rec.get('附件链接', '') or rec.get('pdfUrl', '')
                if pdf_url and not pdf_url.startswith('http'):
                    pdf_url = 'http://www.szse.cn' + pdf_url
                
                publish_date = rec.get('公告时间', rec.get('公布时间', ''))
                
                reports.append({
                    'title': title,
                    'announcementId': rec.get('公告ID', ''),
                    'publishDate': publish_date,
                    'pdfUrl': pdf_url,
                    'category': '年报' if '年度' in title else ('半年报' if '半年度' in title else '季报'),
                    'exchange': 'SZSE',
                    'stockCode': stock_code,
                })
        
        return reports
    
    except Exception as e:
        print(f"  ⚠️ SZSE API请求失败: {e}")
        return []


def fetch_all_exchange_reports(stock_code, report_type='all'):
    """获取所有交易所的财报公告"""
    all_reports = []
    
    if is_shenzhen(stock_code):
        print("📡 查询深交所...")
        szse_reports = fetch_szse_reports(stock_code, report_type)
        all_reports.extend(szse_reports)
        print(f"  深交所找到 {len(szse_reports)} 份报告")
    else:
        # 上交所（包含科创板688/787）
        print("📡 查询上交所...")
        sse_reports = fetch_sse_reports(stock_code, report_type)
        all_reports.extend(sse_reports)
        print(f"  上交所找到 {len(sse_reports)} 份报告")
        
        # 科创板同时查一下是否有补充披露
        if is_kechuang_board(stock_code):
            print("📡 查询科创板补充披露...")
            time.sleep(0.3)
    
    # 去重
    seen = set()
    unique = []
    for r in all_reports:
        key = (r.get('title'), r.get('publishDate'))
        if key not in seen:
            seen.add(key)
            unique.append(r)
    
    # 按日期排序（最新优先）
    unique.sort(key=lambda x: x.get('publishDate', ''), reverse=True)
    
    return unique


# ─────────────────────────────────────────
# PDF下载
# ─────────────────────────────────────────

def download_report_pdf(pdf_url, output_path, timeout=60):
    """下载财报PDF"""
    if not pdf_url:
        return False, "URL为空"
    
    # 确保URL完整
    if not pdf_url.startswith('http'):
        return False, f"无效URL: {pdf_url}"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': 'http://www.sse.com.cn/',
        'Accept': 'application/pdf,*/*',
    }
    
    try:
        response = requests.get(pdf_url, headers=headers, timeout=timeout, stream=True)
        
        if response.status_code == 200:
            content_type = response.headers.get('Content-Type', '')
            
            # 检查是否真的是PDF
            content = b''
            for chunk in response.iter_content(chunk_size=65536):
                content += chunk
                if len(content) > 20:
                    break
            
            # PDF magic bytes: %PDF
            if content[:4] == b'%PDF':
                with open(output_path, 'wb') as f:
                    f.write(content)
                    # 继续下载剩余内容
                    for chunk in response.iter_content(chunk_size=65536):
                        f.write(chunk)
                size = os.path.getsize(output_path)
                return True, f"下载成功 ({size//1024}KB)"
            else:
                # 尝试找重定向的真实PDF链接
                if b'location' in content[:500].lower():
                    # HTML重定向
                    try:
                        text = content.decode('utf-8', errors='ignore')
                        redirect_match = re.search(r'["\']?([^"\']+\.pdf)["\']?', text)
                        if redirect_match:
                            redirect_url = redirect_match.group(1)
                            if not redirect_url.startswith('http'):
                                redirect_url = pdf_url.split('/announcement/')[0] + redirect_url
                            return download_report_pdf(redirect_url, output_path, timeout)
                    except:
                        pass
                return False, f"不是PDF文件 (Content-Type: {content_type})"
        else:
            return False, f"HTTP {response.status_code}"
    
    except requests.exceptions.Timeout:
        return False, "下载超时"
    except requests.exceptions.ConnectionError:
        return False, "连接失败"
    except Exception as e:
        return False, str(e)


# ─────────────────────────────────────────
# PDF解析（核心）
# ─────────────────────────────────────────

def parse_financial_pdf(pdf_path):
    """
    解析财报PDF，提取所有重要财务数据和附注
    返回结构化数据字典
    """
    result = {
        'file': pdf_path,
        'text_length': 0,
        'financial_statements': {},
        'footnotes': {},
        'quarterly_data': {},
        'business_analysis': {},
        'key_warnings': [],
    }
    
    if not os.path.exists(pdf_path):
        result['error'] = "文件不存在"
        return result
    
    try:
        with pdfplumber.open(pdf_path) as pdf:
            all_text = ""
            all_pages = []
            
            # 第一阶段：提取所有文本
            for i, page in enumerate(pdf.pages):
                try:
                    text = page.extract_text()
                    if text:
                        all_text += f"\n===== PAGE {i+1} =====\n{text}"
                        all_pages.append({'page': i+1, 'text': text})
                except Exception as e:
                    continue
                
                # 提取表格（财务数据主要在表格中）
                try:
                    tables = page.extract_tables()
                    if tables:
                        for t_idx, table in enumerate(tables):
                            if table and len(table) > 0:
                                result['tables'] = result.get('tables', [])
                                result['tables'].append({
                                    'page': i+1,
                                    'table_idx': t_idx,
                                    'data': table
                                })
                except Exception:
                    pass
            
            result['text_length'] = len(all_text)
            all_text_lower = all_text.lower()
            
            # 第二阶段：提取财务报表
            result['financial_statements'] = extract_financial_statements(all_text)
            
            # 第三阶段：提取附注（关键！）
            result['footnotes'] = extract_footnotes(all_text, all_text_lower)
            
            # 第四阶段：提取分季度数据
            result['quarterly_data'] = extract_quarterly_data(all_text)
            
            # 第五阶段：提取董事会报告
            result['business_analysis'] = extract_business_analysis(all_text)
            
            # 第六阶段：关键警示
            result['key_warnings'] = detect_key_warnings(all_text, all_text_lower, result)
            
    except Exception as e:
        result['error'] = str(e)
    
    return result


def extract_financial_statements(text):
    """
    提取三大财务报表数据
    重点：资产负债表、利润表、现金流量表
    """
    statements = {}
    
    # ── 利润表 ──
    income_patterns = {
        '营业收入': r'营业收入[^\d]*([\d,，.]+(?:\.\d+)?)\s*(?:元|万元|百万元|亿元)?',
        '营业成本': r'营业成本[^\d]*([\d,，.]+(?:\.\d+)?)\s*(?:元|万元|百万元|亿元)?',
        '净利润': r'净利润[^\d]*([\d,，.]+(?:\.\d+)?)\s*(?:元|万元|百万元|亿元)?',
        '扣非净利润': r'扣非[^\d]*([\d,，.]+(?:\.\d+)?)\s*(?:元|万元|百万元|亿元)?',
        '投资收益': r'投资收益[^\d]*([\d,，.]+(?:\.\d+)?)\s*(?:元|万元|百万元|亿元)?',
        '营业利润': r'营业利润[^\d]*([\d,，.]+(?:\.\d+)?)\s*(?:元|万元|百万元|亿元)?',
        '利润总额': r'利润总额[^\d]*([\d,，.]+(?:\.\d+)?)\s*(?:元|万元|百万元|亿元)?',
    }
    
    income_data = {}
    for name, pattern in income_patterns.items():
        matches = re.findall(pattern, text)
        if matches:
            # 取第一个匹配（通常是当年数据）
            val_str = matches[0].replace(',', '').replace('，', '')
            try:
                income_data[name] = float(val_str)
            except ValueError:
                income_data[name] = matches[0]
    
    if income_data:
        statements['income'] = income_data
    
    # ── 资产负债表 ──
    balance_patterns = {
        '货币资金': r'货币资金[^\d]*([\d,，.]+(?:\.\d+)?)\s*(?:元|万元|百万元|亿元)?',
        '应收账款': r'应收账款[^\d]*([\d,，.]+(?:\.\d+)?)\s*(?:元|万元|百万元|亿元)?',
        '存货': r'存货[^\d]*([\d,，.]+(?:\.\d+)?)\s*(?:元|万元|百万元|亿元)?',
        '固定资产': r'固定资产[^\d]*([\d,，.]+(?:\.\d+)?)\s*(?:元|万元|百万元|亿元)?',
        '在建工程': r'在建工程[^\d]*([\d,，.]+(?:\.\d+)?)\s*(?:元|万元|百万元|亿元)?',
        '应付账款': r'应付账款[^\d]*([\d,，.]+(?:\.\d+)?)\s*(?:元|万元|百万元|亿元)?',
        '短期借款': r'短期借款[^\d]*([\d,，.]+(?:\.\d+)?)\s*(?:元|万元|百万元|亿元)?',
        '长期借款': r'长期借款[^\d]*([\d,，.]+(?:\.\d+)?)\s*(?:元|万元|百万元|亿元)?',
        '总资产': r'资产总计[^\d]*([\d,，.]+(?:\.\d+)?)\s*(?:元|万元|百万元|亿元)?',
        '总负债': r'负债合计[^\d]*([\d,，.]+(?:\.\d+)?)\s*(?:元|万元|百万元|亿元)?',
        '净资产': r'所有者权益合计[^\d]*([\d,，.]+(?:\.\d+)?)\s*(?:元|万元|百万元|亿元)?',
    }
    
    balance_data = {}
    for name, pattern in balance_patterns.items():
        matches = re.findall(pattern, text)
        if matches:
            val_str = matches[0].replace(',', '').replace('，', '')
            try:
                balance_data[name] = float(val_str)
            except ValueError:
                balance_data[name] = matches[0]
    
    if balance_data:
        statements['balance'] = balance_data
    
    # ── 现金流量表 ──
    cashflow_patterns = {
        '经营CF净额': r'经营活动产生的现金流量净额[^\d]*([-]?[\d,，.]+(?:\.\d+)?)\s*(?:元|万元|百万元|亿元)?',
        '经营CF流入': r'经营活动现金流入小计[^\d]*([\d,，.]+(?:\.\d+)?)\s*(?:元|万元|百万元|亿元)?',
        '经营CF流出': r'经营活动现金流出小计[^\d]*([\d,，.]+(?:\.\d+)?)\s*(?:元|万元|百万元|亿元)?',
        '投资CF净额': r'投资活动产生的现金流量净额[^\d]*([-]?[\d,，.]+(?:\.\d+)?)\s*(?:元|万元|百万元|亿元)?',
        '筹资CF净额': r'筹资活动产生的现金流量净额[^\d]*([-]?[\d,，.]+(?:\.\d+)?)\s*(?:元|万元|百万元|亿元)?',
        '期末现金': r'期末现金及现金等价物余额[^\d]*([\d,，.]+(?:\.\d+)?)\s*(?:元|万元|百万元|亿元)?',
    }
    
    cashflow_data = {}
    for name, pattern in cashflow_patterns.items():
        matches = re.findall(pattern, text)
        if matches:
            val_str = matches[0].replace(',', '').replace('，', '')
            try:
                cashflow_data[name] = float(val_str)
            except ValueError:
                cashflow_data[name] = matches[0]
    
    if cashflow_data:
        statements['cashflow'] = cashflow_data
    
    return statements


def extract_footnotes(text, text_lower):
    """
    提取财务报表附注（最重要！包含大量关键信息）
    
    附注通常包括：
    1. 公司基本情况
    2. 会计政策和会计估计变更
    3. 应收账款账龄分析（重要！）
    4. 存货分类
    5. 关联交易明细
    6. 担保/诉讼/或有事项
    7. 分部信息
    8. 重要合同
    """
    footnotes = {}
    
    # ── 1. 应收账款账龄（核心！） ──
    ar_aging_patterns = [
        # 标准格式：1年以内、1-2年、2-3年、3年以上
        r'应收账款.*?账龄(?:分析|结构|情况)[^\n]*?\n([\s\S]{100,2000}?)(?=\n\d{1,2}\s*[\.、]|\n[A-Z]|\n公司|帐龄|其他)',
        r'账龄.*?1年以内[^\n]*?\n([\s\S]{200,3000}?)(?=\n[A-Z]|\n公司|帐龄)',
        # 表格形式
        r'(?:1年以内|信用期内)[^\d]*?([\d,，.]+)\s*(?:万|元|%).*?(?:1至2年|1-2年)[^\d]*?([\d,，.]+)',
        r'账龄(?:分析|构成|情况|结构)[^\n]*?\n(?:[\s\S]{0,100})?(?:1年以内|信用期)[^\n]*?\n([\s\S]{500,3000}?)(?=\n[A-Z]{2,}|\n主要|账龄|其他)',
    ]
    
    ar_aging_text = ""
    for pattern in ar_aging_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        if matches:
            ar_aging_text = matches[0] if isinstance(matches[0], str) else str(matches[0])
            break
    
    if ar_aging_text:
        # 提取具体数字
        aging_data = {}
        
        # 1年以内
        within_1y = re.findall(r'(?:1年以内|信用期内|未逾期)[^\d]*?([\d,，.]+)', ar_aging_text, re.IGNORECASE)
        if within_1y:
            aging_data['1年以内'] = within_1y[0].replace(',', '').replace('，', '')
        
        # 1-2年
        y1_2 = re.findall(r'(?:1至2年|1-2年)[^\d]*?([\d,，.]+)', ar_aging_text, re.IGNORECASE)
        if y1_2:
            aging_data['1-2年'] = y1_2[0].replace(',', '').replace('，', '')
        
        # 2-3年
        y2_3 = re.findall(r'(?:2至3年|2-3年)[^\d]*?([\d,，.]+)', ar_aging_text, re.IGNORECASE)
        if y2_3:
            aging_data['2-3年'] = y2_3[0].replace(',', '').replace('，', '')
        
        # 3年以上
        over_3y = re.findall(r'(?:3年以上|3至4年|4年至5年|5年以上)[^\d]*?([\d,，.]+)', ar_aging_text, re.IGNORECASE)
        if over_3y:
            aging_data['3年以上'] = over_3y[0].replace(',', '').replace('，', '')
        
        # 提取比例
        ratios = re.findall(r'(?:比例|占比|比率)[^\d]*?(\d+(?:\.\d+)?)\s*%', ar_aging_text)
        
        footnotes['应收账款账龄'] = {
            'text': ar_aging_text[:500],  # 保留前500字原文
            'extracted': aging_data,
            'ratios': ratios[:8],
        }
    
    # ── 2. 关联交易（核心！） ──
    rpt_patterns = [
        r'关联交易[^\n]{0,100}\n([\s\S]{500,5000}?)(?=\n[A-Z]{2,}|\n公司|担保|承诺)',
        r'(?:关联(?:方)?交易|关联方及关联交易的)[^\n]*?\n([\s\S]{500,5000}?)(?=\n[A-Z]{2,}|\n主要|\n担保)',
    ]
    
    rpt_text = ""
    for pattern in rpt_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        if matches:
            rpt_text = matches[0] if isinstance(matches[0], str) else str(matches[0])
            break
    
    if rpt_text:
        # 提取金额
        amounts = re.findall(r'([\d,，.]+)\s*(?:万|亿)?\s*(?:元|人民币|美元)?', rpt_text)
        
        # 提取关键内容
        key_items = re.findall(r'(?:采购|销售|服务|租赁|担保|借款)[^\n]{0,200}', rpt_text)
        
        footnotes['关联交易'] = {
            'text': rpt_text[:800],
            'amounts_found': amounts[:20],
            'key_items': key_items[:10],
        }
    
    # ── 3. 担保/或有事项（核心！） ──
    guarantee_patterns = [
        r'(?:对外担保|关联担保|担保|或有事项|未决诉讼|仲裁)[^\n]{0,50}\n([\s\S]{300,3000}?)(?=\n[A-Z]{2,}|\n公司|\n承诺)',
    ]
    
    guarantee_text = ""
    for pattern in guarantee_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        if matches:
            guarantee_text = matches[0] if isinstance(matches[0], str) else str(matches[0])
            break
    
    if guarantee_text:
        footnotes['担保与或有事项'] = {
            'text': guarantee_text[:600],
        }
    
    # ── 4. 存货明细 ──
    inventory_patterns = [
        r'存货[^\n]{0,50}\n([\s\S]{300,2000}?)(?=\n[A-Z]{2,}|\n公司|固定资产|生物资产)',
    ]
    
    inv_text = ""
    for pattern in inventory_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        if matches:
            inv_text = matches[0] if isinstance(matches[0], str) else str(matches[0])
            break
    
    if inv_text:
        footnotes['存货明细'] = {'text': inv_text[:400]}
    
    # ── 5. 会计政策/估计变更 ──
    if any(kw in text_lower for kw in ['会计政策变更', '会计估计变更', '前期差错', '追溯调整']):
        policy_changes = re.findall(
            r'(?:会计政策变更|会计估计变更|前期差错更正)[^\n]{0,100}\n([\s\S]{200,1500}?)(?=\n[A-Z]{2,}|\n公司)',
            text, re.IGNORECASE
        )
        if policy_changes:
            footnotes['会计政策变更'] = {'text': policy_changes[0][:500]}
    
    # ── 6. 分部信息 ──
    segment_patterns = [
        r'(?:分部信息|分行业|分地区|行业分部|地区分部)[^\n]{0,50}\n([\s\S]{300,2000}?)(?=\n[A-Z]{2,}|\n公司|母公司)',
    ]
    
    for pattern in segment_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        if matches:
            footnotes['分部信息'] = {'text': matches[0][:500]}
            break
    
    # ── 7. 承诺事项 ──
    if '承诺' in text_lower:
        commitment_text = re.findall(
            r'承诺[^\n]{0,50}\n([\s\S]{200,1500}?)(?=\n[A-Z]{2,}|\n公司|担保)',
            text, re.IGNORECASE
        )
        if commitment_text:
            footnotes['承诺事项'] = {'text': commitment_text[0][:400]}
    
    return footnotes


def extract_quarterly_data(text):
    """
    提取分季度数据
    年报中通常有按季度披露的收入、利润数据
    """
    quarterly = {}
    
    # 寻找"分季度主要财务指标"或"季度数据"
    q_patterns = [
        r'(?:分季度(?:的)?(?:主要)?财务指标|季度财务数据|季度收入|季度利润)[^\n]*?\n([\s\S]{500,3000}?)(?=\n[A-Z]{2,}|\n公司|审计|意见)',
        r'(?:Q1|Q2|Q3|Q4|第一季度|第二季度|第三季度|第四季度)[^\n]*?(?:营业收入|净利润|归属于)[^\n]*?\n([\s\S]{500,3000}?)(?=\n[A-Z]{2,}|\n公司)',
    ]
    
    for pattern in q_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        if matches:
            q_text = matches[0] if isinstance(matches[0], str) else str(matches[0])
            
            # 提取各季度收入
            for q_name, q_key in [('Q1', '第一'), ('Q2', '第二'), ('Q3', '第三'), ('Q4', '第四')]:
                # 季度营业收入
                rev_match = re.findall(
                    rf'{q_key}季度[^\d]*?(?:营业[^\d]*?)?收入[^\d]*?([\d,，.]+)\s*(?:万|亿)?',
                    q_text, re.IGNORECASE
                )
                if rev_match:
                    quarterly[f'{q_name}_营收'] = rev_match[0].replace(',', '').replace('，', '')
                
                # 季度净利润
                profit_match = re.findall(
                    rf'{q_key}季度[^\d]*?(?:归属[^\d]*?)?净利润[^\d]*?([\d,，.]+)\s*(?:万|亿)?',
                    q_text, re.IGNORECASE
                )
                if profit_match:
                    quarterly[f'{q_name}_净利润'] = profit_match[0].replace(',', '').replace('，', '')
            
            break
    
    return quarterly


def extract_business_analysis(text):
    """
    提取董事会报告中的经营分析
    """
    analysis = {}
    
    # 营业收入/利润分析
    rev_analysis = re.findall(
        r'(?:营业收入|主营业务收入|净利润)[^\n]{0,200}(?:变动|变化|增减|同比)[^\n]{0,500}',
        text, re.IGNORECASE
    )
    if rev_analysis:
        analysis['收入利润变动说明'] = [r[:300] for r in rev_analysis[:5]]
    
    # 现金流分析
    cf_analysis = re.findall(
        r'现金流[^\n]{0,200}(?:变动|同比|变化)[^\n]{0,300}',
        text, re.IGNORECASE
    )
    if cf_analysis:
        analysis['现金流分析'] = [r[:300] for r in cf_analysis[:3]]
    
    # 主要供应商/客户
    top_client = re.findall(r'前五名客户[^\n]{0,300}', text, re.IGNORECASE)
    if top_client:
        analysis['前五名客户'] = top_client[0][:200]
    
    top_supplier = re.findall(r'前五名供应商[^\n]{0,300}', text, re.IGNORECASE)
    if top_supplier:
        analysis['前五名供应商'] = top_supplier[0][:200]
    
    return analysis


def detect_key_warnings(text, text_lower, parsed_data):
    """
    从PDF全文和解析结果中检测关键风险警示
    这些信息通常藏在附注里
    """
    warnings = []
    
    # ── 1. 应收账款异常 ──
    fs = parsed_data.get('financial_statements', {})
    balance = fs.get('balance', {})
    footnotes = parsed_data.get('footnotes', {})
    
    # 账龄数据中有3年以上应收账款
    ar_aging = footnotes.get('应收账款账龄', {})
    if ar_aging:
        if ar_aging.get('extracted', {}).get('3年以上'):
            warnings.append({
                'type': '🔴 严重',
                'item': '应收账款账龄异常',
                'detail': f"存在3年以上应收账款: {ar_aging['extracted']['3年以上']}，需关注回收情况"
            })
        
        # 1年以内比例过低
        ratios = ar_aging.get('ratios', [])
        if ratios:
            try:
                first_ratio = float(ratios[0])
                if first_ratio < 70:
                    warnings.append({
                        'type': '⚠️ 警示',
                        'item': '应收账款账龄结构恶化',
                        'detail': f"1年以内应收账款仅占{first_ratio}%，账龄结构需关注"
                    })
            except (ValueError, IndexError):
                pass
    
    # ── 2. 担保异常 ──
    guarantee = footnotes.get('担保与或有事项', {})
    if guarantee:
        gt_text = guarantee.get('text', '')
        # 检查是否有大额担保
        担保_amounts = re.findall(r'([\d,，.]+)\s*(?:亿|万)\s*(?:元)?', gt_text)
        if 担保_amounts:
            try:
                max_amt = max(float(a.replace(',','').replace('，','')) for a in 担保_amounts)
                if max_amt > 10000:  # 万元以上
                    warnings.append({
                        'type': '🔴 严重',
                        'item': '存在大额担保或或有事项',
                        'detail': f"附注披露担保金额最高达{担保_amounts[0]}万元，需评估代偿风险"
                    })
            except (ValueError, NameError):
                pass
    
    # ── 3. 关联交易异常 ──
    rpt = footnotes.get('关联交易', {})
    if rpt:
        rpt_text = rpt.get('text', '')
        if any(kw in rpt_text for kw in ['资金占用', '违规担保', '非经营性', '掏空']):
            warnings.append({
                'type': '🔴 严重',
                'item': '关联交易存在资金占用嫌疑',
                'detail': '附注中存在"资金占用"或"非经营性"关联交易表述，需深入调查'
            })
    
    # ── 4. 会计政策变更 ──
    policy_change = footnotes.get('会计政策变更', {})
    if policy_change:
        warnings.append({
            'type': '⚠️ 警示',
            'item': '存在会计政策或估计变更',
            'detail': policy_change.get('text', '')[:200]            })
    
    # ── 5. 在建工程长期不转固 ──
    balance = fs.get('balance', {})
    construction = balance.get('在建工程', 0)
    if construction:
        # 从附注中查找转固信息
        con_text = re.findall(r'在建工程[^\n]{0,100}\n([\s\S]{200,1500}?)(?=\n[A-Z]{2,})', text, re.IGNORECASE)
        if con_text and any(kw in con_text[0] for kw in ['利息费用化', '长期不转固', '进度停滞', '停工']):
            warnings.append({
                'type': '⚠️ 警示',
                'item': '在建工程存在异常',
                'detail': '附注提及在建工程存在利息费用化或进度停滞，需关注转固时间'
            })
    
    # ── 6. 大额商誉减值风险 ──
    if '商誉' in text_lower:
        goodwill_text = re.findall(r'商誉[^\n]{0,100}\n?([\s\S]{200,1500}?)(?=\n[A-Z]{2,})', text, re.IGNORECASE)
        if goodwill_text:
            gw_amounts = re.findall(r'商誉[^\d]*?([\d,，.]+)\s*(?:万|亿)?', goodwill_text[0])
            if gw_amounts:
                warnings.append({
                    'type': '⚠️ 警示',
                    'item': '存在商誉',
                    'detail': f'商誉金额: {gw_amounts[0]}，需关注减值测试结果'
                })
    
    # ── 7. 审计保留意见 ──
    audit_keywords = ['保留意见', '无法表示意见', '否定意见', '带强调事项段']
    for kw in audit_keywords:
        if kw in text:
            warnings.append({
                'type': '🔴 严重',
                'item': f'审计意见: {kw}',
                'detail': '非标准审计意见，需高度重视'
            })
    
    # ── 8. 持续经营能力存疑 ──
    concern_keywords = ['持续经营', '重大不确定', '可能导致公司无法持续经营', '可变现净值低于成本']
    for kw in concern_keywords:
        if kw in text_lower:
            warnings.append({
                'type': '🔴 严重',
                'item': '持续经营能力存疑',
                'detail': f'附注提及: {kw}'
            })
            break
    
    return warnings


# ─────────────────────────────────────────
# 主流程
# ─────────────────────────────────────────

def main(stock_code, output_dir=".", report_type="all", max_reports=5):
    print(f"\n{'='*60}")
    print(f"交易所财报PDF获取与解析 — {stock_code}")
    print(f"{'='*60}\n")
    
    os.makedirs(output_dir, exist_ok=True)
    
    # 1. 获取财报公告列表
    print(f"📡 正在从交易所获取{stock_code}的财报公告列表...")
    reports = fetch_all_exchange_reports(stock_code, report_type)
    
    if not reports:
        print("❌ 无法从交易所获取财报列表，尝试其他方式...")
        return None
    
    print(f"\n找到 {len(reports)} 份财报")
    for i, r in enumerate(reports[:10]):
        print(f"  [{r.get('category','?')}] {r.get('publishDate','?')} | {r.get('title','?')[:40]}")
    
    # 2. 下载PDF
    print(f"\n📥 开始下载PDF（共{len(reports)}份，最多下载{max_reports}份）...")
    downloaded = []
    
    for i, report in enumerate(reports[:max_reports]):
        title = report.get('title', '未知')
        pdf_url = report.get('pdfUrl', '')
        category = report.get('category', 'report')
        publish_date = report.get('publishDate', 'nodate')
        
        date_str = publish_date[:10].replace('-', '') if publish_date else 'nodate'
        safe_title = ''.join(c for c in title[:20] if c not in '/\\:*?"<>|')
        filename = f"{category}_{date_str}_{safe_title}.pdf"
        output_path = os.path.join(output_dir, filename)
        
        print(f"\n[{i+1}/{min(len(reports), max_reports)}] {category} | {title[:50]}")
        
        if not pdf_url:
            print(f"  ⚠️ 无PDF链接，跳过")
            continue
        
        success, msg = download_report_pdf(pdf_url, output_path)
        if success:
            print(f"  ✅ {msg}")
            downloaded.append({
                'report': report,
                'path': output_path,
            })
        else:
            print(f"  ⚠️ {msg}")
        
        time.sleep(0.3)  # 避免请求过快
    
    if not downloaded:
        print("\n❌ 没有任何PDF下载成功")
        return None
    
    # 3. 解析PDF
    print(f"\n📋 开始解析PDF（共{len(downloaded)}份）...")
    all_results = []
    
    for item in downloaded:
        pdf_path = item['path']
        title = item['report'].get('title', '')
        category = item['report'].get('category', '')
        
        print(f"\n📄 解析: {os.path.basename(pdf_path)}")
        
        parsed = parse_financial_pdf(pdf_path)
        
        # 输出关键信息
        print(f"  文本长度: {parsed.get('text_length', 0)} 字符")
        
        # 财务报表
        fs = parsed.get('financial_statements', {})
        if fs:
            income = fs.get('income', {})
            balance = fs.get('balance', {})
            cf = fs.get('cashflow', {})
            
            print(f"  📊 利润表: {len(income)}项 | 资产负债表: {len(balance)}项 | 现金流量表: {len(cf)}项")
            
            if income:
                print(f"    营业收入: {income.get('营业收入', 'N/A')} | 净利润: {income.get('净利润', 'N/A')}")
            if balance:
                print(f"    总资产: {balance.get('总资产', 'N/A')} | 总负债: {balance.get('总负债', 'N/A')}")
            if cf:
                print(f"    经营CF: {cf.get('经营CF净额', 'N/A')}")
        
        # 附注
        fn = parsed.get('footnotes', {})
        if fn:
            print(f"  📌 附注提取: {list(fn.keys())}")
        
        # 警示
        warnings = parsed.get('key_warnings', [])
        if warnings:
            print(f"  ⚠️ 风险警示: {len(warnings)}项")
            for w in warnings[:3]:
                print(f"    {w.get('type','⚠️')} {w.get('item','?')}: {str(w.get('detail',''))[:80]}")
        
        item['parsed'] = parsed
        all_results.append(item)
    
    # 4. 保存结果
    print(f"\n{'='*60}")
    print("解析结果汇总")
    print(f"{'='*60}")
    
    # 保存结构化JSON
    summary = {
        'stock_code': stock_code,
        'fetch_time': datetime.now().isoformat(),
        'reports_found': len(reports),
        'downloaded': len(downloaded),
        'results': []
    }
    
    for item in all_results:
        result_entry = {
            'title': item['report'].get('title'),
            'category': item['report'].get('category'),
            'publish_date': item['report'].get('publishDate'),
            'pdf_path': item['path'],
            'text_length': item['parsed'].get('text_length'),
            'financial_statements': item['parsed'].get('financial_statements', {}),
            'footnotes': {k: (v if not isinstance(v, dict) or 'text' not in v else {'text': v.get('text','')[:500]}) 
                         for k, v in item['parsed'].get('footnotes', {}).items()},
            'quarterly_data': item['parsed'].get('quarterly_data', {}),
            'key_warnings': item['parsed'].get('key_warnings', []),
        }
        summary['results'].append(result_entry)
    
    output_json = os.path.join(output_dir, f"exchange_reports_{stock_code}.json")
    with open(output_json, 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    
    print(f"\n✅ 结构化数据已保存: {output_json}")
    
    # 输出最重要的警示
    all_warnings = []
    for item in all_results:
        all_warnings.extend(item['parsed'].get('key_warnings', []))
    
    if all_warnings:
        print(f"\n{'='*60}")
        print(f"⚠️ 关键风险警示（共{len(all_warnings)}项）")
        print(f"{'='*60}")
        # 按严重程度排序
        all_warnings.sort(key=lambda x: 0 if '🔴' in x.get('type','') else (1 if '⚠️' in x.get('type','') else 2))
        for w in all_warnings:
            print(f"  {w.get('type','⚠️')} {w.get('item','?')}")
            print(f"    {str(w.get('detail',''))[:120]}")
    
    return summary


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python3 exchange_report_fetcher.py <股票代码> [输出目录] [--type annual|half|quarterly|all] [--max N]")
        print("\n示例:")
        print("  python3 exchange_report_fetcher.py 688351 ./reports --type annual --max 3")
        print("  python3 exchange_report_fetcher.py 002014 ./reports --type all --max 5")
        sys.exit(1)
    
    code = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else "."
    report_type = "all"
    max_reports = 5
    
    args = sys.argv[3:]
    for i, arg in enumerate(args):
        if arg == '--type' and i+1 < len(args):
            report_type = args[i+1]
        elif arg == '--max' and i+1 < len(args):
            max_reports = int(args[i+1])
    
    main(code, output_dir, report_type, max_reports)
