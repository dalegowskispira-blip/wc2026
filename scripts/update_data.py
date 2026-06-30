#!/usr/bin/env python3
"""
2026世界杯数据自动更新脚本
- 从 football-data.org 拉取最新比分
- 比赛结束后调用 Claude API 生成复盘分析
- 更新 data/matches.json 和 data/predictions.json
"""

import json
import os
import time
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
    "South Korea": "韩国", "Ivory Coast": "科特迪瓦",
    "Bosnia-Herzegovina": "波黑", "Bosnia and Herz": "波黑",
    "Congo DR": "刚果(金)", "Cape Verde Islands": "佛得角",
    "Czech Republic": "捷克",
}


# ─────────────────────────────────────────
# 从 predictions.json 读取预测数据
# ─────────────────────────────────────────
def load_predictions_map() -> dict:
    try:
        with open(PREDICTIONS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        pred_map = data.get("predictions", {})
        print(f"✅ 从 predictions.json 加载预测数据，共 {len(pred_map)} 场")
        return pred_map
    except Exception as e:
        print(f"⚠️  加载预测数据失败: {e}，将跳过复盘生成")
        return {}


def get_predicted_score(pred: dict) -> str:
    """Bug1修复：优先读旧字段 top_score，没有则从新结构 scores.main[0] 取。"""
    if pred.get("top_score"):
        return pred["top_score"]
    sc = pred.get("scores")
    if isinstance(sc, dict):
        return (sc.get("main") or ["?"])[0]
    if isinstance(sc, list) and sc:
        return sc[0].get("s", "?")
    return "?"


# ─────────────────────────────────────────
# 1. 拉取比赛数据
# ─────────────────────────────────────────
def fetch_live_scores():
    """从 football-data.org 拉取世界杯比分"""
    if not FOOTBALL_API_KEY:
        print("⚠️  未配置 FOOTBALL_API_KEY，跳过API拉取")
        return None

    headers = {"X-Auth-Token": FOOTBALL_API_KEY}
    url = "https://api.football-data.org/v4/competitions/WC/matches"

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
    with open(MATCHES_FILE, encoding="utf-8") as f:
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

        # 点球大战处理：football-data 的 fullTime 会把点球数并进总比分
        # (例 90/120分钟 1-1、点球 3-4 → fullTime 返回 4-5)。
        # 这里拆出真实的法定比分(home_score/away_score)与点球比分(home_pen/away_pen)。
        pens = score.get("penalties") or {}
        ph, pa = pens.get("home"), pens.get("away")
        is_shootout = (score.get("duration") == "PENALTY_SHOOTOUT") or (ph is not None and pa is not None)
        if is_shootout and hs is not None and as_ is not None and ph is not None and pa is not None:
            hs, as_ = hs - ph, as_ - pa  # 还原为法定（含加时）比分

        utc_date_str = api_m.get("utcDate", "")
        bjt_date = utc_to_bjt_date(utc_date_str)

        for local_id, local_m in local_matches.items():
            if local_m["home"] == home and local_m["away"] == away:
                changed = False
                if bjt_date and local_m.get("date") != bjt_date:
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
                # 点球比分写入独立字段（非点球场清空，避免残留）
                new_ph = ph if is_shootout else None
                new_pa = pa if is_shootout else None
                if local_m.get("home_pen") != new_ph:
                    local_m["home_pen"] = new_ph
                    changed = True
                if local_m.get("away_pen") != new_pa:
                    local_m["away_pen"] = new_pa
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
# 3. 用 Claude 生成赛后复盘（含重试）
# ─────────────────────────────────────────
def generate_review(home: str, away: str, actual_score: str, predicted: dict,
                    max_retries: int = 3, retry_interval: int = 5) -> dict | None:
    if not ANTHROPIC_API_KEY:
        print("  ⚠️  未配置 ANTHROPIC_API_KEY，跳过复盘生成")
        return None

    hs, as_ = actual_score.split("-")
    hs, as_ = int(hs), int(as_)
    actual_result = "主队胜" if hs > as_ else "平局" if hs == as_ else "客队胜"
    pred_result = (
        "主队胜" if predicted["win"] > predicted["loss"] and predicted["win"] > predicted["draw"]
        else "平局" if predicted["draw"] >= predicted["win"] and predicted["draw"] >= predicted["loss"]
        else "客队胜"
    )
    is_correct = pred_result == actual_result
    # Bug1修复：用辅助函数取比分，不直接访问 top_score
    top_score = get_predicted_score(predicted)

    prompt = f"""你是一位专业足球数据分析师。请完成以下步骤：

第一步：用 web_search 搜索关键词「{home} {away} 2026世界杯 赛后」，获取真实赛后报道。

第二步：基于搜索结果，输出一个 JSON 对象（只输出 JSON，不要有任何其他文字、不要有 markdown 代码块）：

{{
  "key_player": "本场最佳或最关键球员姓名",
  "reason": "150字以内的复盘。必须包含：①进球者姓名和大致时间；②比赛关键转折点（如红牌/VAR/扑救）；③预测{'正确' if is_correct else '失误'}的主要原因。如果 web_search 没有找到相关报道，请在开头注明"未找到赛后报道，基于比分推断"，再给出推断性分析。"
}}

比赛信息（供参考）：
- 对阵：{home} vs {away}
- 实际比分：{actual_score}（{actual_result}）
- AI赛前预测：{pred_result}（胜{predicted['win']}% / 平{predicted['draw']}% / 负{predicted['loss']}%）
- 预测最可能比分：{top_score}
- 预测结果：{'✅ 正确' if is_correct else '❌ 错误'}"""

    import anthropic
    import re

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    for attempt in range(1, max_retries + 1):
        try:
            msg = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=600,
                tools=[{"type": "web_search_20250305", "name": "web_search"}],
                messages=[{"role": "user", "content": prompt}],
            )

            text = "".join(block.text for block in msg.content if hasattr(block, "text"))

            clean = re.sub(r"```(?:json)?|```", "", text).strip()
            match = re.search(r'\{.*?\}', clean, re.DOTALL)
            if match:
                result = json.loads(match.group())
                result["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                print(f"  ✅ 复盘生成成功（第{attempt}次尝试）：{result.get('key_player', '未知')}")
                return result
            else:
                raise ValueError(f"响应中未找到有效JSON，原始内容：{text[:200]}")

        except Exception as e:
            print(f"  ⚠️  第{attempt}次尝试失败: {e}")
            if attempt < max_retries:
                print(f"  ⏳ {retry_interval}秒后重试...")
                time.sleep(retry_interval)
            else:
                print(f"  ❌ 已达最大重试次数，放弃生成复盘")

    return None


# ─────────────────────────────────────────
# 4. 更新 predictions.json
# ─────────────────────────────────────────
def update_predictions(matches, predictions_map: dict):
    with open(PREDICTIONS_FILE, encoding="utf-8") as f:
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
        hs, as_ = m["home_score"], m["away_score"]
        actual_result = "主胜" if hs > as_ else "平局" if hs == as_ else "客胜"

        # 正向/反向查预测数据
        key = f"{home}|{away}"
        rev_key = f"{away}|{home}"
        pred = predictions_map.get(key) or predictions_map.get(rev_key)

        if not pred:
            continue  # 没有预测数据的比赛跳过，不写入 records

        pred_result = (
            "主胜" if pred["win"] > pred["loss"] and pred["win"] > pred["draw"]
            else "平局" if pred["draw"] >= pred["win"] and pred["draw"] >= pred["loss"]
            else "客胜"
        )
        is_correct = pred_result == actual_result
        # Bug1修复：用辅助函数，不直接访问 top_score
        predicted_score = get_predicted_score(pred)

        print(f"  处理: {home} {actual_score} {away} → 预测{'✅' if is_correct else '❌'}")

        review = generate_review(home, away, actual_score, pred)

        record = {
            "match_id": m["id"],
            "home": home,
            "away": away,
            "predicted": pred_result,
            "actual": actual_result,
            "predicted_score": predicted_score,
            "actual_score": actual_score,
            "result": "correct" if is_correct else "wrong",
            "confidence": pred.get("confidence", "中"),
            "review": review,
        }

        pred_data["records"].append(record)
        existing_ids.add(m["id"])
        new_records += 1

    # 重新计算总成绩（unknown 不计入 correct/wrong 分母）
    counted = [r for r in pred_data["records"] if r["result"] in ("correct", "wrong")]
    total = len(counted)
    correct = sum(1 for r in counted if r["result"] == "correct")
    pred_data["summary"] = {
        "total": len(pred_data["records"]),
        "correct": correct,
        "wrong": total - correct,
        "accuracy": round(correct / total * 100, 1) if total > 0 else 0,
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

    predictions_map = load_predictions_map()
    api_matches = fetch_live_scores()
    matches = update_matches(api_matches)
    update_predictions(matches, predictions_map)

    print("✅ 全部完成")
