# 2026 世界杯 · AI预测看板

自动更新的世界杯预测数据看板，每小时自动抓取最新比分，AI自动生成赛后复盘。

## 功能
- 📅 赛程预测（胜平负概率 + 比分概率分布）
- 🎯 预测战绩（成功率统计 + 逐场AI复盘分析）
- 📊 小组积分榜
- 📋 历史比分查询
- 🏳️ 球队详情与球员能力六边形

## 部署配置

### 需要在 GitHub Secrets 中添加两个密钥：

1. **`FOOTBALL_API_KEY`**
   - 来自：https://www.football-data.org/
   - 注册免费账号（每分钟10次请求限额，足够用）
   - 复制 API Token 填入

2. **`ANTHROPIC_API_KEY`**
   - 来自：https://console.anthropic.com/
   - 用于生成赛后AI复盘分析

### 添加方式：
仓库页面 → Settings → Secrets and variables → Actions → New repository secret

### 启用 GitHub Pages：
仓库页面 → Settings → Pages → Source 选 "Deploy from a branch" → Branch: main → / (root) → Save

## 数据说明
- `data/matches.json` — 完整赛程 + 实时比分（自动更新）
- `data/predictions.json` — 预测记录 + AI复盘（比赛结束后自动生成）
- `scripts/update_data.py` — 数据更新脚本（GitHub Actions 每小时运行）

## 访问密码
`honghao`
