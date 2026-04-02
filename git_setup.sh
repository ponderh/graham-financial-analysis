#!/usr/bin/env bash
# 格雷厄姆分析Skill - Git初始化脚本
# 用法: bash git_setup.sh [GitHub用户名] [仓库名]
# 例如: bash git_setup.sh myaccount graham-financial-analysis

SKILL_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SKILL_DIR"

# 检查是否已初始化
if [ -d ".git" ]; then
    echo "⚠️  Git仓库已存在，跳过初始化"
else
    echo "📦 初始化Git仓库..."
    git init
    git add .
    git commit -m "feat: 初始化格雷厄姆财务报表分析Skill

- SKILL.md: 主框架文档
- scripts/: 数据采集/分析脚本
- references/: 格雷厄姆原则/框架/RedFlag参考
- assets/: 报告模板
- git_setup.sh: Git管理脚本"
    echo "✅ Git仓库初始化完成"
fi

# 处理GitHub远程仓库
if [ -n "$1" ] && [ -n "$2" ]; then
    REPO="https://github.com/$1/$2.git"
    if git remote get-url origin 2>/dev/null | grep -q "github.com"; then
        echo "⚠️  remote origin 已存在"
    else
        echo "🔗 添加远程仓库: $REPO"
        git remote add origin "$REPO"
        echo "✅ 远程仓库添加完成"
        echo ""
        echo "📋 下一步操作:"
        echo "  1. 在GitHub上创建空仓库: https://github.com/new"
        echo "     仓库名: $2"
        echo "     不要勾选 Initialize repository"
        echo "  2. 推送代码:"
        echo "     git push -u origin main"
    fi
else
    echo ""
    echo "📋 GitHub设置步骤:"
    echo "  1. 在GitHub上创建空仓库"
    echo "  2. 运行: bash git_setup.sh <你的用户名> <仓库名>"
fi
