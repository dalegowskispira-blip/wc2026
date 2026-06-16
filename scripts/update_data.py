#!/usr/bin/env python3
"""
2026世界杯数据自动更新脚本
- 从 football-data.org 拉取最新比分
- 比赛结束后调用 Claude API 生成复盘分析
- 更新 data/matches.json 和 data/predictions.json
"""
 
import json
import os
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path
 
BJT = timezone(timedelta(hours=8))
 
# ─────────────────────────────────────────
# 配置
# ─────────────────────────────────────────
FOOTBALL_API_KEY = os.environ.get("FOOTBALL_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
 
DATA_DIR = Path(__file__).parent.parent / "data"
MATCHES_FILE = DATA_DIR / "matches.json"
PREDICTIONS_FILE = DATA_DIR / "predictions.json"
 
# football-data.org 世界杯赛事ID（2026赛季）
WC2026_COMPETITION_ID = 2000  # 需要根据实际API返回更新
 
# 中文队名映射（API返回英文 → 我们的中文）
TEAM_NAME_MAP = {
    "Mexico": "墨西哥", "South Africa": "南非", "Korea Republic": "韩国",
    "Czechia": "捷克", "Canada": "加拿大", "Bosnia and Herzegovina": "波黑",
    "USA": "美国", "United States": "美国", "Paraguay": "巴拉圭",
    "Qatar": "卡塔尔", "Switzerland": "瑞士", "Brazil": "巴西",
    "Morocco": "摩洛哥", "Scotland": "苏格兰", "Haiti": "海地",
    "Australia": "澳大利亚", "Türkiye": "土耳其", "Turkey": "土耳其",
    "Germany": "德国", "Curaçao": "库拉索", "Netherlands": "荷兰",
    "Japan": "日本", "Côte d'Ivoire": "科特迪瓦", "Ecuador": "厄瓜多尔",
    "Sweden": "瑞典", "Tunisia": "突尼斯", "Spain": "西班牙",
    "Cape Verde": "佛得角", "Belgium": "比利时", "Egypt": "埃及",
    "Saudi Arabia": "沙特", "Uruguay": "乌拉圭", "Iran": "伊朗",
    "New Zealand": "新西兰", "France": "法国", "Senegal": "塞内加尔",
    "Iraq": "伊拉克", "Norway": "挪威", "Argentina": "阿根廷",
    "Algeria": "阿尔及利亚", "Austria": "奥地利", "Jordan": "约旦",
    "Portugal": "葡萄牙", "DR Congo": "刚果(金)", "England": "英格兰",
    "Croatia": "克罗地亚", "Ghana": "加纳", "Panama": "巴拿马",
    "Uzbekistan": "乌兹别克", "Colombia": "哥伦比亚",
}
 
# 预测数据（与 index.html 保持一致，用于赛后核对）
PREDICTIONS_MAP = {
    "西班牙|佛得角":   {"win": 88, "draw": 8,  "loss": 4,  "top_score": "3-0"},
    "比利时|埃及":     {"win": 72, "draw": 18, "loss": 10, "top_score": "2-0"},
    "沙特|乌拉圭":     {"win": 15, "draw": 35, "loss": 50, "top_score": "0-1"},
    "伊朗|新西兰":     {"win": 71, "draw": 20, "loss": 9,  "top_score": "2-0"},
    "法国|塞内加尔":   {"win": 75, "draw": 16, "loss": 9,  "top_score": "2-0"},
    "伊拉克|挪威":     {"win": 18, "draw": 22, "loss": 60, "top_score": "0-2"},
    "阿根廷|阿尔及利亚":{"win": 82, "draw": 12, "loss": 6, "top_score": "3-0"},
    "奥地利|约旦":     {"win": 65, "draw": 22, "loss": 13, "top_score": "2-0"},
    "葡萄牙|刚果(金)": {"win": 84, "draw": 11, "loss": 5,  "top_score": "3-0"},
    "英格兰|克罗地亚": {"win": 58, "draw": 25, "loss": 17, "top_score": "2-1"},
    "加纳|巴拿马":     {"win": 52, "draw": 28, "loss": 20, "top_score": "1-0"},
    "乌兹别克|哥伦比亚":{"win": 22, "draw": 28, "loss": 50, "top_score": "0-2"},
}
 
 
# ─────────────────────────────────────────
# 1. 拉取比赛数据
# ─────────────────────────────────────────
def fetch_live_scores():
    """从 football-data.org 拉取世界杯比分"""
    if not FOOTBALL_API_KEY:
        print("⚠️  未配置 FOOTBALL_API_KEY，跳过API拉取")
        return None
 
    headers = {"X-Auth-Token": FOOTBALL_API_KEY}
    url = f"https://api.football-data.org/v4/competitions/WC/matches"
    
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        print(f"✅ API拉取成功，共 {len(data.get('matches', []))} 场比赛")
        return data.get("matches", [])
    except Exception as e:
        print(f"❌ API拉取失败: {e}")
        return None
 
 
def map_team_name(api_name: str) -> str:
    return TEAM_NAME_MAP.get(api_name, api_name)
 
 
def api_status_to_local(api_status: str) -> str:
    mapping = {
        "FINISHED": "finished",
        "IN_PLAY": "live",
        "PAUSED": "live",
        "SCHEDULED": "upcoming",
        "TIMED": "upcoming",
        "POSTPONED": "postponed",
    }
    return mapping.get(api_status, "upcoming")
 
 
# ─────────────────────────────────────────
# 2. 更新 matches.json
# ─────────────────────────────────────────
def utc_to_bjt_date(utc_str: str) -> str:
    """将UTC时间字符串转为北京时间日期 YYYY-MM-DD"""
    if not utc_str:
        return ""
    try:
        dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
        return dt.astimezone(BJT).strftime("%Y-%m-%d")
    except Exception:
        return utc_str[:10]
 
 
def update_matches(api_matches):
    """将API数据合并进本地 matches.json"""
    with open(MATCHES_FILE) as f:
        local_data = json.load(f)
 
    local_matches = {m["id"]: m for m in local_data["matches"]}
    updated_count = 0
 
    for api_m in (api_matches or []):
        home = map_team_name(api_m.get("homeTeam", {}).get("name", ""))
        away = map_team_name(api_m.get("awayTeam", {}).get("name", ""))
        status = api_status_to_local(api_m.get("status", ""))
        score = api_m.get("score", {})
        full = score.get("fullTime", {})
        hs = full.get("home")
        as_ = full.get("away")
 
        # API返回的比赛时间转为北京时间日期
        utc_date_str = api_m.get("utcDate", "")
        bjt_date = utc_to_bjt_date(utc_date_str)
 
        # 按主客队名匹配本地记录
        for local_id, local_m in local_matches.items():
            if local_m["home"] == home and local_m["away"] == away:
                local_date = local_m.get("date", "")
 
                # 日志：打印每场比赛的时间对比
                print(f"  📅 {home} vs {away}")
                print(f"     API UTC原始时间: {utc_date_str}")
                print(f"     转换后北京时间日期: {bjt_date}")
                print(f"     本地存储日期: {local_date}")
 
                changed = False
 
                # 保护逻辑：如果BJT日期与本地日期相差超过1天，不覆盖日期
                if bjt_date and local_date:
                    try:
                        d_bjt = datetime.strptime(bjt_date, "%Y-%m-%d")
                        d_local = datetime.strptime(local_date, "%Y-%m-%d")
                        diff = abs((d_bjt - d_local).days)
                        if diff > 1:
                            print(f"  ⚠️  日期偏差 {diff} 天（BJT:{bjt_date} vs 本地:{local_date}），跳过日期覆盖，只更新比分和状态")
                        elif bjt_date != local_date:
                            local_m["date"] = bjt_date
                            changed = True
                            print(f"  ✏️  日期更新: {local_date} → {bjt_date}")
                    except ValueError:
                        print(f"  ⚠️  日期解析失败，跳过日期更新")
                elif bjt_date and not local_date:
                    local_m["date"] = bjt_date
                    changed = True
 
                if local_m["status"] != status:
                    local_m["status"] = status
                    changed = True
                if hs is not None and local_m.get("home_score") != hs:
                    local_m["home_score"] = hs
                    changed = True
                if as_ is not None and local_m.get("away_score") != as_:
                    local_m["away_score"] = as_
                    changed = True
                if changed:
                    updated_count += 1
                break
 
    local_data["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    local_data["matches"] = list(local_matches.values())
 
    with open(MATCHES_FILE, "w", encoding="utf-8") as f:
        json.dump(local_data, f, ensure_ascii=False, indent=2)
 
    print(f"✅ matches.json 更新完成，变更 {updated_count} 场")
    return local_data["matches"]
 
 
# ─────────────────────────────────────────
# 3. 用 Claude 生成赛后复盘
# ─────────────────────────────────────────
def generate_review(home: str, away: str, actual_score: str, predicted: dict) -> dict:
    """调用Claude API生成赛后复盘分析"""
    if not ANTHROPIC_API_KEY:
        print(f"  ⚠️  未配置 ANTHROPIC_API_KEY，跳过复盘生成")
        return None
 
    pred_result = "主队胜" if predicted["win"] > predicted["loss"] and predicted["win"] > predicted["draw"] else \
                  "平局" if predicted["draw"] >= predicted["win"] and predicted["draw"] >= predicted["loss"] else "客队胜"
 
    hs, as_ = actual_score.split("-")
    hs, as_ = int(hs), int(as_)
    actual_result = "主队胜" if hs > as_ else "平局" if hs == as_ else "客队胜"
    is_correct = pred_result == actual_result
 
    prompt = f"""你是一位专业足球数据分析师，请用中文对以下比赛进行赛后复盘分析：
 
比赛：{home} vs {away}
实际比分：{actual_score}
AI赛前预测：{pred_result}（胜率{predicted['win']}% / 平{predicted['draw']}% / 负{predicted['loss']}%）
预测最可能比分：{predicted['top_score']}
预测是否正确：{'✅ 正确' if is_correct else '❌ 错误'}
 
请搜索该场比赛的真实赛后报道，然后输出一个JSON对象（只输出JSON，不要有其他文字）：
{{
  "key_player": "本场最关键球员姓名",
  "reason": "100字左右的复盘分析，说明：1)预测{'正确' if is_correct else '失误'}的主要原因，2)哪名球员超常/失常发挥，3)哪个关键时刻影响了结果"
}}"""
 
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=500,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            messages=[{"role": "user", "content": prompt}]
        )
        # 提取文本内容
        text = ""
        for block in msg.content:
            if hasattr(block, "text"):
                text += block.text
 
        # 解析JSON
        import re
        match = re.search(r'\{[^{}]+\}', text, re.DOTALL)
        if match:
            result = json.loads(match.group())
            result["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            print(f"  ✅ 复盘生成成功：{result['key_player']}")
            return result
    except Exception as e:
        print(f"  ❌ 复盘生成失败: {e}")
    return None
 
 
# ─────────────────────────────────────────
# 4. 更新 predictions.json
# ─────────────────────────────────────────
def update_predictions(matches):
    """检查刚结束的比赛，生成预测记录和复盘"""
    with open(PREDICTIONS_FILE) as f:
        pred_data = json.load(f)
 
    existing_ids = {r["match_id"] for r in pred_data["records"]}
    new_records = 0
 
    for m in matches:
        if m["status"] != "finished":
            continue
        if m["id"] in existing_ids:
            continue
 
        home = m["home"]
        away = m["away"]
        actual_score = f"{m['home_score']}-{m['away_score']}"
 
        # 查找预测
        key = f"{home}|{away}"
        rev_key = f"{away}|{home}"
        pred = PREDICTIONS_MAP.get(key) or PREDICTIONS_MAP.get(rev_key)
        if not pred:
            continue  # 没有预测数据的跳过
 
        hs, as_ = m["home_score"], m["away_score"]
        actual_result = "主胜" if hs > as_ else "平局" if hs == as_ else "客胜"
        pred_result = "主胜" if pred["win"] > pred["loss"] and pred["win"] > pred["draw"] else \
                      "平局" if pred["draw"] >= pred["win"] and pred["draw"] >= pred["loss"] else "客胜"
        is_correct = pred_result == actual_result
 
        print(f"  处理: {home} {actual_score} {away} → 预测{'✅' if is_correct else '❌'}")
 
        # 生成复盘
        review = None
        if not is_correct or actual_score != pred["top_score"]:
            review = generate_review(home, away, actual_score, pred)
 
        record = {
            "match_id": m["id"],
            "home": home,
            "away": away,
            "predicted": pred_result,
            "actual": actual_result,
            "predicted_score": pred["top_score"],
            "actual_score": actual_score,
            "result": "correct" if is_correct else "wrong",
            "confidence": "中",
            "review": review
        }
 
        pred_data["records"].append(record)
        existing_ids.add(m["id"])
        new_records += 1
 
    # 重新计算总成绩
    total = len(pred_data["records"])
    correct = sum(1 for r in pred_data["records"] if r["result"] == "correct")
    pred_data["summary"] = {
        "total": total,
        "correct": correct,
        "wrong": total - correct,
        "accuracy": round(correct / total * 100, 1) if total > 0 else 0
    }
    pred_data["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
 
    with open(PREDICTIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(pred_data, f, ensure_ascii=False, indent=2)
 
    print(f"✅ predictions.json 更新，新增 {new_records} 条，准确率 {pred_data['summary']['accuracy']}%")
 
 
# ─────────────────────────────────────────
# 主流程
# ─────────────────────────────────────────
if __name__ == "__main__":
    print(f"🚀 开始更新 [{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}]")
    
    api_matches = fetch_live_scores()
    matches = update_matches(api_matches)
    update_predictions(matches)
    
    print("✅ 全部完成")
 
