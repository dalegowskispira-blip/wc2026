#!/usr/bin/env python3
"""
Generate match analysis using Claude with web_search.
Test mode (default): runs only the next upcoming match within 7 days.
Full mode: python generate_analysis.py --all
"""
import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import anthropic

BASE_DIR = Path(__file__).parent.parent
MATCHES_FILE = BASE_DIR / "data" / "matches.json"
PREDICTIONS_FILE = BASE_DIR / "data" / "predictions.json"
MODEL = "claude-opus-4-8"
MAX_RETRIES = 3

SYSTEM_PROMPT = """你是一个专业足球分析师，任务是为2026世界杯小组赛比赛生成预测数据。

请先用web_search搜索以下信息：
1. 两支球队的近期状态（近5场比赛）
2. 球队伤病/停赛情况
3. 历史交锋记录
4. 本届世界杯已有表现（如有）

然后返回一个严格的JSON对象，格式如下：
{
  "win": <主队获胜概率，整数，0-100>,
  "draw": <平局概率，整数，0-100>,
  "loss": <客队获胜概率，整数，0-100>,
  "lean": "<主胜|平局|客胜>",
  "scores": {
    "main": ["<最可能比分1>", "<最可能比分2>"],
    "secondary": ["<次可能比分1>", "<次可能比分2>"],
    "upset": ["<爆冷比分>"]
  },
  "analysis": "<100-150字的中文分析，包含：双方近期状态、关键球员、战术分析、预测理由。禁止编造具体比赛数据>",
  "confidence": "<高|中高|中|低>"
}

要求：
- win+draw+loss必须等于100
- lean必须与win/draw/loss中最大值对应
- 比分格式为"主队得分-客队得分"
- analysis必须基于搜索到的真实信息，不得编造
- 只返回JSON，不要有任何其他文字"""


def get_bjt_now():
    bjt = timezone(timedelta(hours=8))
    return datetime.now(bjt)


def get_bjt_date_str(dt):
    return dt.strftime("%Y-%m-%d")


def load_data():
    with open(MATCHES_FILE, "r", encoding="utf-8") as f:
        matches = json.load(f)["matches"]
    with open(PREDICTIONS_FILE, "r", encoding="utf-8") as f:
        predictions = json.load(f)
    return matches, predictions


def get_target_matches(matches, test_mode=True):
    now = get_bjt_now()
    today = get_bjt_date_str(now)
    cutoff = get_bjt_date_str(now + timedelta(days=7))

    # Debug: print all upcoming matches found in the file
    all_upcoming = [m for m in matches if m.get("status") == "upcoming"]
    print(f"[DEBUG] BJT now: {now.strftime('%Y-%m-%d %H:%M')} (UTC+8)")
    print(f"[DEBUG] Looking for upcoming matches from {today} to {cutoff}")
    print(f"[DEBUG] All upcoming matches in matches.json ({len(all_upcoming)} total):")
    for m in sorted(all_upcoming, key=lambda m: (m.get("date", ""), m.get("bjt", ""))):
        print(f"         {m.get('date')} {m.get('bjt','?'):>5}  {m['home']} vs {m['away']}")

    # Filter: status=upcoming AND date within next 7 days
    upcoming = [
        m for m in all_upcoming
        if today <= m.get("date", "") <= cutoff
    ]
    upcoming.sort(key=lambda m: (m.get("date", ""), m.get("bjt", "99:99")))

    print(f"[DEBUG] Matches within 7 days ({len(upcoming)} found):")
    for m in upcoming:
        print(f"         {m.get('date')} {m.get('bjt','?'):>5}  {m['home']} vs {m['away']}")
    print()

    if test_mode:
        return [upcoming[0]] if upcoming else []

    return upcoming


def generate_prediction(match, client):
    home, away = match["home"], match["away"]
    group = match.get("group", "?")
    bjt = match.get("bjt", "?")
    date = match.get("date", "?")

    user_prompt = (
        f"{home} vs {away}，2026世界杯小组赛，{group}组，"
        f"北京时间{date} {bjt}开赛。请搜索两队最新状态后给出预测。"
    )

    messages = [{"role": "user", "content": user_prompt}]
    tools = [{"type": "web_search_20250305", "name": "web_search"}]

    while True:
        response = client.messages.create(
            model=MODEL,
            max_tokens=2000,
            system=SYSTEM_PROMPT,
            tools=tools,
            messages=messages,
        )

        if response.stop_reason == "end_turn":
            break

        if response.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": response.content})
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    # web_search results come back in block.content
                    result_content = getattr(block, "content", None)
                    if result_content is None:
                        result_content = "(no result)"
                    elif not isinstance(result_content, str):
                        result_content = json.dumps(result_content, ensure_ascii=False)
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result_content,
                        }
                    )
            messages.append({"role": "user", "content": tool_results})
        else:
            # max_tokens or other stop
            break

    text = next(
        (b.text for b in response.content if hasattr(b, "text") and b.type == "text"),
        "",
    )
    return parse_prediction_json(text), text


def parse_prediction_json(text):
    # Try code block first
    code_match = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text)
    if code_match:
        return json.loads(code_match.group(1))
    # Try bare JSON object
    obj_match = re.search(r"\{[\s\S]*\}", text)
    if obj_match:
        return json.loads(obj_match.group())
    raise ValueError(f"No JSON found in response:\n{text[:500]}")


def save_to_predictions(match, pred_data, predictions_data):
    key = f"{match['home']}|{match['away']}"
    existing = predictions_data.get("predictions", {}).get(key, {})
    if existing.get("analysis"):
        print(f"[SKIP] {key} — analysis already exists")
        return False

    if "predictions" not in predictions_data:
        predictions_data["predictions"] = {}
    predictions_data["predictions"][key] = pred_data

    with open(PREDICTIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(predictions_data, f, ensure_ascii=False, indent=2)

    print(f"[SAVED] {key}")
    return True


def main():
    test_mode = "--all" not in sys.argv

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)
    matches, predictions_data = load_data()
    targets = get_target_matches(matches, test_mode=test_mode)

    if not targets:
        print("No upcoming matches found in the next 7 days.")
        return

    mode_label = "TEST MODE (1 match)" if test_mode else f"FULL MODE ({len(targets)} matches)"
    print(f"=== {mode_label} ===\n")

    for match in targets:
        home, away = match["home"], match["away"]
        print(f">>> Processing: {home} vs {away} ({match.get('date')} {match.get('bjt')})")

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                pred, raw_text = generate_prediction(match, client)

                print("\n--- Full JSON ---")
                print(json.dumps(pred, ensure_ascii=False, indent=2))
                print("\n--- Analysis ---")
                print(pred.get("analysis", "(none)"))
                print()

                save_to_predictions(match, pred, predictions_data)
                break

            except json.JSONDecodeError as e:
                print(f"[Attempt {attempt}] JSON parse error: {e}")
                if attempt == MAX_RETRIES:
                    print(f"[SKIP] {home} vs {away} — failed to parse after {MAX_RETRIES} attempts")
            except Exception as e:
                print(f"[Attempt {attempt}] Error: {e}")
                if attempt == MAX_RETRIES:
                    print(f"[SKIP] {home} vs {away} — gave up after {MAX_RETRIES} attempts")


if __name__ == "__main__":
    main()
