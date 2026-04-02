---
name: graham-financial-analysis
description: 格雷厄姆式A股财务报表深度分析Skill。当需要对A股上市公司进行基本面投资分析、使用格雷厄姆/巴菲特价值投资框架、进行多专家协作财务分析、下载并分析年报PDF、或对特定股票进行系统性财务尽调时使用此Skill。触发词："格雷厄姆分析"、"财务报表深度分析"、"价值投资分析"、"多专家协作分析"、"年报PDF分析"。
---

# 格雷厄姆式A股财务报表分析

## 工作流程

### 阶段1：数据采集

**使用 scripts/data_fetch.py 采集数据：**

```bash
python3 scripts/data_fetch.py <股票代码> <输出目录>
# 例如：python3 scripts/data_fetch.py 002014 ./analysis
```

采集内容：
- 综合财务指标（86+字段，akshare东方财富接口）
- 利润表、资产负债表、现金流量表
- 公司基本信息
- 股价历史（前复权）

**年报PDF下载（可选，用于交叉验证）：**

巨潮资讯PDF直链格式：
```
http://static.cninfo.com.cn/finalpage/<日期>/<公告ID>.PDF
```

公告ID需从巨潮网页或akshare `stock_zh_a_disclosure_report_cninfo`接口获取。
如akshare报brotli错误，用curl直接下载：
```bash
curl -s -L -o <output>.pdf "http://static.cninfo.com.cn/finalpage/<日期>/<ID>.PDF"
```

### 阶段2：多专家协作分析

**必须用 sessions_spawn 并行启动三个子任务：**

1. **专家A（芒格式商业洞察）** → 模块1-4（盈利质量/财务稳定/运营效率/现金流）
2. **专家B（量化估值派）** → 模块5-8（估值/护城河/管理层/同业比较）
3. **质疑者（批判性思维）** → 框架评审 + 过程评估 + 系统性挑战

**分工文件：**
- 详细框架：references/framework.md
- 格雷厄姆核心原则：references/graham_principles.md
- Red Flag清单：references/red_flags.md
- 分析报告模板：assets/report_template.md

### 阶段3：数据计算脚本

**scripts/analyze_modules.py** — 精确计算核心指标：

```python
python3 scripts/analyze_modules.py <股票代码> <数据目录>
```

计算内容：
- 格雷厄姆数（保守版 + 成长调整版）
- 净现比三年趋势
- 上下游占款能力
- 毛利率CV稳定性系数
- 历史PE/PB分位

### 阶段4：报告撰写与发送

**报告必须包含（见模板）：**
1. 八维评分卡（每模块1-10分）
2. 格雷厄姆内在价值区间（保守/中性/乐观）
3. 安全边际计算（折扣率）
4. 核心Red Flag清单（8项逐条核查）
5. 三方分歧点说明
6. 最终投资结论（强烈推荐/推荐/中性/回避 + 操作建议）

**发送飞书：**
```python
python3 scripts/send_feishu.py "<飞书open_id>" "<报告摘要>"
```

## 格雷厄姆核心原则（分析时必须遵守）

1. **现金流是真相**：净现比（经营CF/净利润）是格雷厄姆最重视的单一指标
2. **安全边际第一**：永远不在高于内在价值的价格买入
3. **盈利稳定性**：要求7-10年数据，A股至少用3年+季度跟踪
4. **分散投资**：单一股票不超过总仓位的25%
5. **定性+定量**：数字是底线，判断靠常识

## 关键阈值速查

| 指标 | 安全 | 警示 | 危险 |
|------|------|------|------|
| 净现比 | >1.0 | 0.8-1.0 | <0.8 |
| 资产负债率（制造业） | <40% | 40-50% | >50% |
| ROE | >15% | 10-15% | <10% |
| 格雷厄姆数折扣 | >20%折扣 | 10-20% | <10% |
| 有息负债率 | <20% | 20-40% | >40% |

## 常见问题处理

**akshare报brotli错误**：换用curl直接下载，或用东方财富接口作为备选
**年报PDF下载失败**：巨潮PDF链接有固定格式 `http://static.cninfo.com.cn/finalpage/YYYY-MM-DD/<ID>.PDF`
**数据与PDF不符**：以年报PDF为准，akshare仅供参考
**三位专家结论分歧**：以质疑者的挑战为核心，判断分歧是否影响最终结论

## Git管理规范

所有分析项目必须纳入git版本控制：
```bash
cd <项目目录>
git init  # 首次
git add .
git commit -m "feat: <股票> <分析阶段>"
git push  # 定期推送
```

上传GitHub前确保：
- 不含敏感信息（API密钥等）
- 不含大型数据文件（>10MB用git-lfs）
