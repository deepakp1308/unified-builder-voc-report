#!/usr/bin/env python3
"""
Weekly VOC Report Generator

Pulls new messages from #hvc_feedback and #mc-hvc-escalations since last run,
appends to data/analysis.json, and regenerates index.html.

Usage:
    export SLACK_BOT_TOKEN=xoxb-...
    python scripts/generate_report.py
"""

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

CHANNELS = {
    "C051Y4H98VB": "hvc_feedback",
    "C095FJ3SQF4": "mc-hvc-escalations",
}

BUILDER_KEYWORDS = [
    "email builder", "new builder", "legacy builder", "classic builder",
    "template editor", "campaign builder", "drag and drop", "content block",
    "nuni", "nea", "freddie", "unified builder",
]

DATA_FILE = Path(__file__).parent.parent / "data" / "analysis.json"
HTML_FILE = Path(__file__).parent.parent / "index.html"


def get_slack_client() -> WebClient:
    token = os.environ.get("SLACK_BOT_TOKEN")
    if not token:
        print("ERROR: SLACK_BOT_TOKEN environment variable not set")
        sys.exit(1)
    return WebClient(token=token)


def load_data() -> dict:
    if DATA_FILE.exists():
        with open(DATA_FILE) as f:
            return json.load(f)
    return {"metadata": {}, "sentiment": {}, "themes": [], "issues": [], "weekly_deltas": []}


def save_data(data: dict):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)


def pull_messages(client: WebClient, channel_id: str, oldest: str) -> list[dict]:
    """Pull all messages from a channel since oldest timestamp."""
    messages = []
    cursor = None
    while True:
        try:
            kwargs = {
                "channel": channel_id,
                "oldest": oldest,
                "limit": 100,
            }
            if cursor:
                kwargs["cursor"] = cursor
            response = client.conversations_history(**kwargs)
            messages.extend(response.get("messages", []))
            cursor = response.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break
            time.sleep(1.2)
        except SlackApiError as e:
            if e.response["error"] == "ratelimited":
                retry_after = int(e.response.headers.get("Retry-After", 5))
                time.sleep(retry_after)
                continue
            print(f"Slack API error: {e}")
            break
    return messages


def parse_hvc_feedback(msg: dict) -> dict | None:
    """Parse structured survey response from #hvc_feedback."""
    text = msg.get("text", "")
    if not text or "Survey Response" not in text and "Response from" not in text:
        return None

    result = {
        "ts": msg.get("ts", ""),
        "channel": "hvc_feedback",
        "date": datetime.fromtimestamp(float(msg.get("ts", "0")), tz=timezone.utc).strftime("%Y-%m-%d"),
    }

    mrr_match = re.search(r"\*MRR:\*\s*(\d[\d,]*)", text)
    if mrr_match:
        result["mrr"] = int(mrr_match.group(1).replace(",", ""))

    uid_match = re.search(r"\*User ID:\*\s*(\d+)", text)
    if uid_match:
        result["user_id"] = uid_match.group(1)

    plan_match = re.search(r"\*Plan:\*\s*(.+?)[\n*]", text)
    if plan_match:
        result["plan"] = plan_match.group(1).strip()

    prs_match = re.search(r"\*PRS:\*\s*(\d+)", text)
    if prs_match:
        score = int(prs_match.group(1))
        result["prs"] = score
        result["sentiment"] = "positive" if score >= 9 else ("neutral" if score >= 7 else "negative")

    csat_match = re.search(r"\*CSAT:\*\s*(.+?)[\n*]", text)
    if csat_match:
        rating = csat_match.group(1).strip().lower()
        result["csat"] = rating
        if rating in ("excellent", "good", "hervorragend", "buona", "satisfecho", "muy satisfecho"):
            result["sentiment"] = "positive"
        elif rating in ("average", "moyennes", "mittel", "medianamente satisfecho", "intermedia"):
            result["sentiment"] = "neutral"
        else:
            result["sentiment"] = "negative"

    feedback_match = re.search(r"\*Feedback:\*\s*(.+?)(?:\n\n|\*FS|\*Fullstory|____)", text, re.DOTALL)
    if feedback_match:
        result["feedback"] = feedback_match.group(1).strip()[:500]

    builder_match = re.search(r"\*Email Builder:\*\s*(.+?)[\n*]", text)
    if builder_match:
        result["email_builder"] = builder_match.group(1).strip()

    return result


def parse_escalation(msg: dict) -> dict | None:
    """Parse structured escalation from #mc-hvc-escalations."""
    text = msg.get("text", "")
    if "Product Feedback Received" not in text and "HVC" not in text:
        return None

    result = {
        "ts": msg.get("ts", ""),
        "channel": "mc-hvc-escalations",
        "date": datetime.fromtimestamp(float(msg.get("ts", "0")), tz=timezone.utc).strftime("%Y-%m-%d"),
        "sentiment": "negative",
    }

    name_match = re.search(r"\*Customer Name\*\n(.+?)(?:\n|$)", text)
    if name_match:
        result["customer_name"] = name_match.group(1).strip()

    mrr_match = re.search(r"\*?MRR\*?\n(\d[\d,]*)", text)
    if mrr_match:
        result["mrr"] = int(mrr_match.group(1).replace(",", ""))

    uid_match = re.search(r"\*?Customer UID\*?\n(\d+)", text)
    if uid_match:
        result["user_id"] = uid_match.group(1)

    product_match = re.search(r"\*Impacted Product\*\n(.+?)(?:\n|$)", text)
    if product_match:
        result["impacted_product"] = product_match.group(1).strip()

    goal_match = re.search(r"\*Goal:.*?\*\s*\n(.+?)(?:\*Constraints|\n\n)", text, re.DOTALL)
    if goal_match:
        result["feedback"] = goal_match.group(1).strip()[:500]

    return result


def classify_theme(feedback: str) -> str:
    """Simple keyword-based theme classification."""
    text = feedback.lower() if feedback else ""

    if any(w in text for w in ["slow", "lag", "loading", "unresponsive", "performance"]):
        return "Performance & Slow"
    if any(w in text for w in ["render", "preview", "inbox", "outlook", "mobile", "desktop", "looks different"]):
        return "Rendering Issues"
    if any(w in text for w in ["migrate", "legacy", "old builder", "classic", "parity", "switch builder"]):
        return "Migration & Legacy"
    if any(w in text for w in ["save", "lost", "vanish", "error occurred", "reload", "autosave"]):
        return "Save/Lost Work"
    if any(w in text for w in ["support", "chatbot", "human", "wait", "hold", "escalat"]):
        return "Support Frustration"
    if any(w in text for w in ["drag", "drop", "steps", "confusing", "find", "navigate", "clunky", "intuitive"]):
        return "Usability & Workflow"
    if any(w in text for w in ["font", "format", "spacing", "alignment", "bullet", "line break"]):
        return "Formatting Controls"
    if any(w in text for w in ["ai", "freddie", "intuit assist", "generated draft"]):
        return "AI/Freddie Issues"
    if any(w in text for w in ["change", "moved", "used to", "different now", "without notice"]):
        return "UI Keeps Changing"
    if any(w in text for w in ["feature", "missing", "dark mode", "video", "reusable", "dynamic content"]):
        return "Missing Features"
    return "Other"


def deduplicate(items: list[dict]) -> list[dict]:
    """Deduplicate by user_id + theme per calendar month."""
    seen = set()
    deduped = []
    for item in items:
        uid = item.get("user_id", item.get("ts", ""))
        theme = item.get("theme", "")
        month = item.get("date", "")[:7]
        key = f"{uid}:{theme}:{month}"
        if key not in seen:
            seen.add(key)
            deduped.append(item)
    return deduped


def compute_weekly_delta(new_items: list[dict]) -> dict:
    """Compute what changed this week."""
    negative = sum(1 for i in new_items if i.get("sentiment") == "negative")
    positive = sum(1 for i in new_items if i.get("sentiment") == "positive")
    total = len(new_items)

    themes = {}
    for item in new_items:
        t = item.get("theme", "Other")
        themes[t] = themes.get(t, 0) + 1

    top_theme = max(themes, key=themes.get) if themes else "N/A"

    total_mrr = sum(item.get("mrr", 0) for item in new_items if item.get("sentiment") == "negative")

    return {
        "week": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "new_items": total,
        "negative": negative,
        "positive": positive,
        "top_theme": top_theme,
        "mrr_at_risk": total_mrr,
    }


def regenerate_html(data: dict):
    """Regenerate index.html from data. Uses the existing template with updated date."""
    if not HTML_FILE.exists():
        print("WARNING: index.html not found, skipping HTML regeneration")
        return

    html = HTML_FILE.read_text()
    today = datetime.now(timezone.utc).strftime("%B %d, %Y")
    html = re.sub(
        r"Last updated: <strong[^>]*>[^<]+</strong>",
        f'Last updated: <strong id="lastUpdated">{today}</strong>',
        html,
    )
    HTML_FILE.write_text(html)
    print(f"Updated index.html timestamp to {today}")


def main():
    print("=" * 60)
    print(f"VOC Report Generator — {datetime.now(timezone.utc).isoformat()}")
    print("=" * 60)

    client = get_slack_client()
    data = load_data()

    last_ts = data.get("last_pull_timestamp", "0")
    print(f"Pulling messages since timestamp: {last_ts}")

    all_new_items = []

    for channel_id, channel_name in CHANNELS.items():
        print(f"\nPulling from #{channel_name} ({channel_id})...")
        messages = pull_messages(client, channel_id, last_ts)
        print(f"  Retrieved {len(messages)} messages")

        for msg in messages:
            if channel_name == "hvc_feedback":
                parsed = parse_hvc_feedback(msg)
            else:
                parsed = parse_escalation(msg)

            if parsed and parsed.get("feedback"):
                parsed["theme"] = classify_theme(parsed.get("feedback", ""))
                all_new_items.append(parsed)

    # Exclude known bot/test accounts
    excluded = set(data.get("metadata", {}).get("excluded_accounts", ["49256993"]))
    all_new_items = [i for i in all_new_items if i.get("user_id") not in excluded]

    # Deduplicate
    all_new_items = deduplicate(all_new_items)
    print(f"\nNew items after dedup: {len(all_new_items)}")

    if all_new_items:
        delta = compute_weekly_delta(all_new_items)
        print(f"Weekly delta: {delta}")

        if "weekly_deltas" not in data:
            data["weekly_deltas"] = []
        data["weekly_deltas"].append(delta)

    # Update last pull timestamp
    data["last_pull_timestamp"] = str(int(time.time()))
    data["metadata"]["generated_at"] = datetime.now(timezone.utc).isoformat()

    save_data(data)
    regenerate_html(data)

    print("\nDone!")
    print(f"  Data saved to: {DATA_FILE}")
    print(f"  Report at: {HTML_FILE}")


if __name__ == "__main__":
    main()
