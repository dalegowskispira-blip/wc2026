#!/usr/bin/env python3
"""
调试脚本：对比 API 返回的 UTC 时间 vs 转换后北京时间 vs 本地存储日期
运行方式：FOOTBALL_API_KEY=xxx python3 scripts/debug_dates.py
"""

import json
import os
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path

BJT = timezone(timedelta(hours=8))

FOOTBALL_API_KEY = os.environ.get("FOOTBALL_API_KEY", "")
DATA_DIR = Path(__file__).parent.parent / "data"
MATCHES_FILE = DATA_DIR / "matches.json"

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


def map_team_name(api_name):
    return TEAM_NAME_MAP.get(api_name, api_name)


def utc_to_bjt_date(utc_str):
    if not utc_str:
        return "N/A"
    try:
        dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
        return dt.astimezone(BJT).strftime("%Y-%m-%d")
    except Exception:
        return "解析失败"


def utc_to_bjt_full(utc_str):
    if not utc_str:
        return "N/A"
    try:
        dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
        return dt.astimezone(BJT).strftime("%Y-%m-%d %H:%M BJT")
    except Exception:
        return "解析失败"


def main():
    # 读本地数据
    with open(MATCHES_FILE) as f:
        local_data = json.load(f)
    local_index = {}
    for m in local_data["matches"]:
        key = f"{m['home']}|{m['away']}"
        local_index[key] = m

    # 拉API
    if not FOOTBALL_API_KEY:
        print("❌ 未设置 FOOTBALL_API_KEY 环境变量")
        print("   运行方式：FOOTBALL_API_KEY=你的key python3 scripts/debug_dates.py")
        return

    print("正在拉取 API 数据...\n")
    headers = {"X-Auth-Token": FOOTBALL_API_KEY}
    try:
        resp = requests.get(
            "https://api.football-data.org/v4/competitions/WC/matches",
            headers=headers, timeout=10
        )
        resp.raise_for_status()
        api_matches = resp.json().get("matches", [])
    except Exception as e:
        print(f"❌ API拉取失败: {e}")
        return

    print(f"{'比赛':<28} {'UTC原始时间':<26} {'转换BJT完整时间':<22} {'BJT日期':<12} {'本地日期':<12} {'偏差'}")
    print("-" * 120)

    mismatch_count = 0
    for api_m in api_matches:
        home = map_team_name(api_m.get("homeTeam", {}).get("name", ""))
        away = map_team_name(api_m.get("awayTeam", {}).get("name", ""))
        utc_str = api_m.get("utcDate", "")
        bjt_date = utc_to_bjt_date(utc_str)
        bjt_full = utc_to_bjt_full(utc_str)

        key = f"{home}|{away}"
        local_m = local_index.get(key)
        local_date = local_m["date"] if local_m else "未找到"

        # 计算偏差
        diff_str = ""
        flag = ""
        if local_date != "未找到" and bjt_date not in ("N/A", "解析失败"):
            try:
                d_bjt = datetime.strptime(bjt_date, "%Y-%m-%d")
                d_local = datetime.strptime(local_date, "%Y-%m-%d")
                diff = (d_bjt - d_local).days
                if diff == 0:
                    diff_str = "✅ 一致"
                elif abs(diff) == 1:
                    diff_str = f"⚠️  {'+' if diff>0 else ''}{diff}天"
                    mismatch_count += 1
                else:
                    diff_str = f"❌ {'+' if diff>0 else ''}{diff}天"
                    mismatch_count += 1
            except ValueError:
                diff_str = "?"
        elif local_date == "未找到":
            diff_str = "—"

        match_str = f"{home} vs {away}"
        print(f"{match_str:<28} {utc_str:<26} {bjt_full:<22} {bjt_date:<12} {local_date:<12} {diff_str}")

    print("-" * 120)
    print(f"\n共 {len(api_matches)} 场，日期不一致 {mismatch_count} 场")
    if mismatch_count > 0:
        print("\n💡 如果偏差固定为 -1天（BJT比本地早一天），说明API的 utcDate 已经是北京时间，不需要再+8小时转换")
        print("   如果偏差固定为 +1天（BJT比本地晚一天），说明转换方向相反，或本地日期写错了")


if __name__ == "__main__":
    main()
