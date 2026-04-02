#!/usr/bin/env python3
"""
年报PDF解析模块
从巨潮资讯PDF年报中提取关键财务数据

功能：
1. 董事会报告中的经营分析文字
2. 分季度收入利润（补充Q1/Q3数据）
3. 财务报表注释（应收账龄/存货明细/关联交易）
4. 现金流量表补充数据

用法: python3 parse_financial_pdf.py <PDF路径> [输出JSON路径]
"""

import sys
import os
import json
import re
import subprocess


def check_pdf_tools():
    """检查可用的PDF解析工具"""
    tools = {}
    
    # pdftotext (poppler-utils)
    try:
        result = subprocess.run(['pdftotext', '-v'], capture_output=True, text=True)
        tools['pdftotext'] = True
    except FileNotFoundError:
        tools['pdftotext'] = False
    
    # pdfplumber (Python库)
    try:
        import pdfplumber
        tools['pdfplumber'] = True
    except ImportError:
        tools['pdfplumber'] = False
    
    # PyPDF2
    try:
        import PyPDF2
        tools['pypdf2'] = True
    except ImportError:
        tools['pypdf2'] = False
    
    return tools


def extract_text_pdftotext(pdf_path):
    """用pdftotext提取文本"""
    try:
        result = subprocess.run(
            ['pdftotext', '-layout', pdf_path, '-'],
            capture_output=True, text=True, timeout=60
        )
        return result.stdout
    except Exception as e:
        return None


def extract_text_pdfplumber(pdf_path):
    """用pdfplumber提取文本和表格"""
    try:
        import pdfplumber
        with pdfplumber.open(pdf_path) as pdf:
            full_text = ""
            tables_data = []
            
            for i, page in enumerate(pdf.pages):
                text = page.extract_text()
                if text:
                    full_text += f"\n--- Page {i+1} ---\n{text}"
                
                # 提取表格
                tables = page.extract_tables()
                if tables:
                    tables_data.append({
                        'page': i + 1,
                        'tables': tables
                    })
            
            return full_text, tables_data
    except Exception as e:
        return None, None


def parse_quarterly_data(text):
    """
    从年报中提取分季度数据
    重点：Q1、Q2、Q3、Q4的单季度收入和利润
    """
    result = {}
    
    if not text:
        return result
    
    # 匹配分季度数据模式
    # 如: "第一季度实现营业收入xxx万元，同比增长xx%"
    quarters = ['一季报', '第一季度', 'Q1', '中期', '第二季度', 'Q2', '三季度', '第三季度', 'Q3', '四季度', 'Q4', '年度报告']
    
    # 提取营业收入
    revenue_patterns = [
        r'(?:营业收入|主营业务收入)[^\d]*([\d,]+(?:\.\d+)?)\s*(?:万|亿)?\s*(?:元|万元|亿元)?',
        r'第[一二三四]季度[^\d]*([\d,]+(?:\.\d+)?)\s*(?:万|亿)?\s*(?:元|万元|亿元)?',
    ]
    
    for pattern in revenue_patterns:
        matches = re.findall(pattern, text)
        if matches:
            result['revenue_matches'] = matches[:8]  # 最多8个匹配
            break
    
    # 提取净利润
    profit_patterns = [
        r'(?:归属于上市公司股东的)?净利润[^\d]*([\d,]+(?:\.\d+)?)\s*(?:万|亿)?\s*(?:元|万元|亿元)?',
        r'扣非净利润[^\d]*([\d,]+(?:\.\d+)?)\s*(?:万|亿)?\s*(?:元|万元|亿元)?',
    ]
    
    for pattern in profit_patterns:
        matches = re.findall(pattern, text)
        if matches:
            result['profit_matches'] = matches[:8]
            break
    
    # 提取经营活动现金流
    cashflow_patterns = [
        r'经营活动产生的现金流量净额[^\d-]*([-]?[\d,]+(?:\.\d+)?)\s*(?:万|亿)?\s*(?:元|万元|亿元)?',
    ]
    
    for pattern in cashflow_patterns:
        matches = re.findall(pattern, text)
        if matches:
            result['cashflow_matches'] = matches[:4]
            break
    
    return result


def parse_accounts_receivable(text):
    """
    从年报附注中提取应收账款账龄数据
    """
    result = {}
    
    if not text:
        return result
    
    # 查找"应收账款"附注部分
    # 寻找类似"1年以内""1-2年"等账龄结构
    aging_pattern = r'(?:1年以内|1至2年|2至3年|3年以上|信用期内|逾期)[^\d]*([\d,]+(?:\.\d+)?)\s*(?:万|亿|%)?'
    matches = re.findall(aging_pattern, text)
    
    if matches:
        result['aging_structure'] = matches
    
    # 提取应收票据、应收账款合计
    ar_total_pattern = r'(?:应收票据|应收账款)[^\d]*([\d,]+(?:\.\d+)?)\s*(?:万|亿)?\s*(?:元|万元|亿元)?'
    ar_totals = re.findall(ar_total_pattern, text)
    if ar_totals:
        result['receivable_totals'] = ar_totals[:4]
    
    return result


def parse_inventory_detail(text):
    """
    从年报附注中提取存货明细
    """
    result = {}
    
    if not text:
        return result
    
    # 存货分类
    inv_categories = [
        '原材料', '在产品', '库存商品', '周转材料', '发出商品',
        '委托加工物资', '半成品', '包装物', '低值易耗品'
    ]
    
    for cat in inv_categories:
        pattern = f'{cat}[^\\d]*([\\d,]+(?:\\.\\d+)?)\\s*(?:万|亿)?(?:元|万元|亿元)?'
        matches = re.findall(pattern, text)
        if matches:
            result[cat] = matches[0]
    
    return result


def parse_related_party_transactions(text):
    """
    从年报中提取关联交易数据
    """
    result = {}
    
    if not text:
        return result
    
    # 关联交易金额
    patterns = [
        r'关联交易[^\d]*([\d,]+(?:\.\d+)?)\s*(?:万|亿)?\s*(?:元|万元|亿元)?',
        r'采购商品[^\d]*([\d,]+(?:\.\d+)?)\s*(?:万|亿)?',
        r'销售商品[^\d]*([\d,]+(?:\.\d+)?)\s*(?:万|亿)?',
    ]
    
    all_transactions = []
    for pattern in patterns:
        matches = re.findall(pattern, text)
        all_transactions.extend(matches[:3])
    
    if all_transactions:
        result['transaction_amounts'] = all_transactions[:6]
    
    return result


def parse_business_analysis(text):
    """
    从董事会报告中提取经营分析文字
    """
    if not text:
        return {}
    
    result = {}
    
    # 提取主要经营数据
    key_metrics = {
        '营业收入': r'营业收入[^\d]*([\d,]+(?:\.\d+)?)\s*(?:万|亿)?',
        '净利润': r'净利润[^\d]*([\d,]+(?:\.\d+)?)\s*(?:万|亿)?',
        '总资产': r'总资产[^\d]*([\d,]+(?:\.\d+)?)\s*(?:万|亿)?',
        '净资产': r'净资产[^\d]*([\d,]+(?:\.\d+)?)\s*(?:万|亿)?',
    }
    
    for name, pattern in key_metrics.items():
        matches = re.findall(pattern, text)
        if matches:
            result[name] = matches[0]
    
    # 提取经营计划或展望
    outlook_patterns = [
        r'(?:经营计划|年度计划|工作计划|下一年度|未来展望)[^\n。]*[。]?',
        r'(?:预计|预期|目标)[^\n。]*[。]?',
    ]
    
    outlook_text = []
    for pattern in outlook_patterns:
        matches = re.findall(pattern, text)
        outlook_text.extend(matches[:3])
    
    if outlook_text:
        result['outlook'] = outlook_text[:5]
    
    # 提取主要供应商/客户信息
    customer_pattern = r'前五名客户[^\n。]*[。]?'
    customer_matches = re.findall(customer_pattern, text)
    if customer_matches:
        result['top_customers'] = customer_matches[0]
    
    supplier_pattern = r'前五名供应商[^\n。]*[。]?'
    supplier_matches = re.findall(supplier_pattern, text)
    if supplier_matches:
        result['top_suppliers'] = supplier_matches[0]
    
    return result


def parse_financial_statements(text):
    """
    提取三大财务报表的关键数据
    """
    result = {}
    
    if not text:
        return result
    
    # 利润表关键科目
    income_items = {
        '营业收入': r'营业收入\s+([\d,]+(?:\.\d+)?)',
        '营业成本': r'营业成本\s+([\d,]+(?:\.\d+)?)',
        '销售费用': r'销售费用\s+([\d,]+(?:\.\d+)?)',
        '管理费用': r'管理费用\s+([\d,]+(?:\.\d+)?)',
        '财务费用': r'财务费用\s+([\d,]+(?:\.\d+)?)',
        '投资收益': r'投资收益\s+([\d,]+(?:\.\d+)?)',
        '净利润': r'净利润\s+([\d,]+(?:\.\d+)?)',
    }
    
    income_data = {}
    for name, pattern in income_items.items():
        matches = re.findall(pattern, text)
        if matches:
            income_data[name] = matches[0]
    
    if income_data:
        result['income_statement'] = income_data
    
    # 资产负债表关键科目
    balance_items = {
        '货币资金': r'货币资金\s+([\d,]+(?:\.\d+)?)',
        '应收账款': r'应收账款\s+([\d,]+(?:\.\d+)?)',
        '存货': r'存货\s+([\d,]+(?:\.\d+)?)',
        '固定资产': r'固定资产\s+([\d,]+(?:\.\d+)?)',
        '在建工程': r'在建工程\s+([\d,]+(?:\.\d+)?)',
        '应付账款': r'应付账款\s+([\d,]+(?:\.\d+)?)',
        '短期借款': r'短期借款\s+([\d,]+(?:\.\d+)?)',
        '长期借款': r'长期借款\s+([\d,]+(?:\.\d+)?)',
        '总资产': r'资产总计\s+([\d,]+(?:\.\d+)?)',
        '总负债': r'负债合计\s+([\d,]+(?:\.\d+)?)',
    }
    
    balance_data = {}
    for name, pattern in balance_items.items():
        matches = re.findall(pattern, text)
        if matches:
            balance_data[name] = matches[0]
    
    if balance_data:
        result['balance_sheet'] = balance_data
    
    # 现金流量表关键科目
    cashflow_items = {
        '经营CF净额': r'经营活动产生的现金流量净额\s+([-]?[\d,]+(?:\.\d+)?)',
        '投资CF净额': r'投资活动产生的现金流量净额\s+([-]?[\d,]+(?:\.\d+)?)',
        '筹资CF净额': r'筹资活动产生的现金流量净额\s+([-]?[\d,]+(?:\.\d+)?)',
    }
    
    cashflow_data = {}
    for name, pattern in cashflow_items.items():
        matches = re.findall(pattern, text)
        if matches:
            cashflow_data[name] = matches[0]
    
    if cashflow_data:
        result['cashflow_statement'] = cashflow_data
    
    return result


def main(pdf_path, output_json=None):
    print(f"\n{'='*60}")
    print(f"年报PDF解析 — {os.path.basename(pdf_path)}")
    print(f"{'='*60}\n")
    
    if not os.path.exists(pdf_path):
        print(f"❌ PDF文件不存在: {pdf_path}")
        return
    
    # 检查工具
    tools = check_pdf_tools()
    print(f"可用工具: pdftotext={'✅' if tools.get('pdftotext') else '❌'}, pdfplumber={'✅' if tools.get('pdfplumber') else '❌'}")
    
    if not any(tools.values()):
        print("❌ 没有可用的PDF解析工具，请安装: pip install pdfplumber 或 apt install poppler-utils")
        return
    
    # 提取文本
    print("\n正在提取PDF文本...")
    full_text = None
    tables_data = None
    
    if tools.get('pdftotext'):
        text = extract_text_pdftotext(pdf_path)
        if text:
            full_text = text
            print(f"  pdftotext提取完成: {len(text)} 字符")
    
    if not full_text and tools.get('pdfplumber'):
        result = extract_text_pdfplumber(pdf_path)
        if result:
            full_text, tables_data = result
            if full_text:
                print(f"  pdfplumber提取完成: {len(full_text)} 字符")
    
    if not full_text:
        print("❌ 无法提取PDF文本")
        return
    
    # 解析各部分
    print("\n正在解析内容...")
    
    result = {
        'pdf_path': pdf_path,
        'quarterly_data': parse_quarterly_data(full_text),
        'accounts_receivable': parse_accounts_receivable(full_text),
        'inventory_detail': parse_inventory_detail(full_text),
        'related_party_transactions': parse_related_party_transactions(full_text),
        'business_analysis': parse_business_analysis(full_text),
        'financial_statements': parse_financial_statements(full_text),
        'tables': tables_data,
        'text_length': len(full_text),
    }
    
    # 输出摘要
    print("\n📋 解析结果摘要:")
    
    ba = result.get('business_analysis', {})
    if ba:
        print(f"\n【董事会报告关键数据】")
        for k, v in ba.items():
            if k != 'outlook':
                print(f"  {k}: {v}")
    
    fs = result.get('financial_statements', {})
    if fs.get('income_statement'):
        print(f"\n【利润表关键科目】")
        for k, v in fs['income_statement'].items():
            print(f"  {k}: {v}")
    
    if fs.get('balance_sheet'):
        print(f"\n【资产负债表关键科目】")
        for k, v in fs['balance_sheet'].items():
            print(f"  {k}: {v}")
    
    if fs.get('cashflow_statement'):
        print(f"\n【现金流量表关键科目】")
        for k, v in fs['cashflow_statement'].items():
            print(f"  {k}: {v}")
    
    qd = result.get('quarterly_data', {})
    if qd:
        print(f"\n【分季度数据线索】")
        for k, v in qd.items():
            print(f"  {k}: {v}")
    
    ar = result.get('accounts_receivable', {})
    if ar:
        print(f"\n【应收账款账龄】")
        for k, v in ar.items():
            print(f"  {k}: {v}")
    
    # 保存JSON
    if output_json:
        json_path = output_json
    else:
        base = os.path.splitext(pdf_path)[0]
        json_path = f"{base}_parsed.json"
    
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    print(f"\n✅ 解析结果已保存: {json_path}")
    print(f"   原始文本长度: {len(full_text)} 字符")
    
    return result


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python3 parse_financial_pdf.py <PDF路径> [输出JSON路径]")
        print("\n示例:")
        print("  python3 parse_financial_pdf.py annual_report_2024.pdf")
        print("  python3 parse_financial_pdf.py annual_report_2024.pdf parsed_2024.json")
        sys.exit(1)
    
    pdf_path = sys.argv[1]
    output_json = sys.argv[2] if len(sys.argv) > 2 else None
    main(pdf_path, output_json)
