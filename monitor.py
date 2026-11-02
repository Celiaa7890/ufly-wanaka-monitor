#!/usr/bin/env python3
"""GitHub Actions monitor for U-Fly Wanaka U-Fly 60 availability."""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from email.header import Header
from zoneinfo import ZoneInfo


BASE_URL = "https://uflywanaka.simplybook.asia"
DATES = [f"2026-11-{day:02d}" for day in range(9, 16)]
STATE_ISSUE_TITLE = "U-Fly monitor state (do not close)"
WORKFLOW_FILE = "ufly-monitor.yml"
USER_AGENT = "UFlyAvailabilityMonitor/3.0 (+personal availability checker)"


def booking_url(day: str) -> str:
    return (
        f"{BASE_URL}/v2/book/location/1/category/1/service/7/count/1/"
        f"provider/any/date/{day}/"
    )


def request_json(url: str, *, method: str = "GET", data=None, headers=None):
    body = None if data is None else json.dumps(data).encode("utf-8")
    request_headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": USER_AGENT,
        **(headers or {}),
    }
    if body is not None:
        request_headers["Content-Type"] = "application/json; charset=utf-8"
    request = urllib.request.Request(
        url, data=body, headers=request_headers, method=method
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = response.read()
        return None if not payload else json.loads(payload)


def fetch_slots(day: str) -> list[dict[str, str]]:
    query = urllib.parse.urlencode(
        {
            "from": day,
            "to": day,
            "location": "1",
            "category": "1",
            "provider": "any",
            "service": "7",
            "count": "1",
        }
    )
    url = f"{BASE_URL}/v2/booking/time-slots/?{query}"
    last_error = None
    for attempt in range(2):
        try:
            request = urllib.request.Request(
                url,
                headers={"Accept": "application/json", "User-Agent": USER_AGENT},
            )
            with urllib.request.urlopen(request, timeout=20) as response:
                body = response.read()
                content_type = response.headers.get("Content-Type", "unknown")
                status = response.status
            if not body.strip():
                raise RuntimeError(f"{day}: empty response")
            try:
                payload = json.loads(body)
            except ValueError as error:
                preview = body[:160].decode("utf-8", errors="replace")
                raise RuntimeError(
                    f"{day}: HTTP {status}, {content_type}, non-JSON response: "
                    f"{preview!r}"
                ) from error
            if not isinstance(payload, list):
                raise RuntimeError(f"{day}: unexpected response")
            return [
                {"day": item.get("date", day), "time": item["time"]}
                for item in payload
                if item.get("type") == "free" and item.get("time")
            ]
        except (OSError, ValueError, RuntimeError) as error:
            last_error = error
            if attempt == 0:
                time.sleep(2)
    raise RuntimeError(str(last_error))


def scan() -> list[dict[str, str]]:
    slots = []
    for day in DATES:
        slots.extend(fetch_slots(day))
    return sorted(slots, key=lambda slot: (slot["day"], slot["time"]))


def github_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def github_api(path: str, *, method: str = "GET", data=None):
    repository = os.environ["GITHUB_REPOSITORY"]
    return request_json(
        f"https://api.github.com/repos/{repository}{path}",
        method=method,
        data=data,
        headers=github_headers(),
    )


def get_state_issue() -> tuple[int | None, dict]:
    issues = github_api("/issues?state=all&per_page=100")
    for issue in issues:
        if issue.get("title") == STATE_ISSUE_TITLE and "pull_request" not in issue:
            try:
                return issue["number"], json.loads(issue.get("body") or "{}")
            except json.JSONDecodeError:
                return issue["number"], {}
    return None, {}


def save_state(issue_number: int | None, state: dict) -> int:
    payload = {"title": STATE_ISSUE_TITLE, "body": json.dumps(state, indent=2)}
    if issue_number is None:
        issue = github_api("/issues", method="POST", data=payload)
        return issue["number"]
    github_api(f"/issues/{issue_number}", method="PATCH", data=payload)
    return issue_number


def send_ntfy(title: str, message: str, click: str) -> None:
    topic = os.environ.get("NTFY_TOPIC", "")
    if not topic:
        raise RuntimeError("NTFY_TOPIC secret is missing")
    request = urllib.request.Request(
        "https://ntfy.sh",
        data=json.dumps(
            {
                "topic": topic,
                "title": title,
                "message": message,
                "priority": 5,
                "tags": ["rotating_light", "airplane"],
                "click": click,
            }
        ).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        if response.status >= 300:
            raise RuntimeError(f"ntfy returned HTTP {response.status}")


def display_time(value: str) -> str:
    return datetime.strptime(value, "%H:%M:%S").strftime("%-I:%M %p")


def disable_expired_workflow() -> bool:
    today = datetime.now(ZoneInfo("Pacific/Auckland")).date()
    if today.isoformat() <= "2026-11-15":
        return False
    github_api(f"/actions/workflows/{WORKFLOW_FILE}/disable", method="PUT")
    print("Monitoring window ended; workflow disabled.")
    return True


def main() -> int:
    if os.environ.get("TEST_NOTIFICATION", "").lower() == "true":
        send_ntfy(
            "U-Fly 云端监测测试成功",
            "这条通知来自 GitHub 云端监测器。以后即使 Mac 睡眠，它也能继续检查并在发现余位时通知你。",
            booking_url(DATES[0]),
        )
        print(json.dumps({"ok": True, "testNotification": True}))
        return 0

    if disable_expired_workflow():
        return 0

    issue_number, previous = get_state_issue()
    previous_slots = set(previous.get("slots", []))

    try:
        current = scan()
        current_keys = {f'{slot["day"]}T{slot["time"]}' for slot in current}
        new_slots = [
            slot
            for slot in current
            if f'{slot["day"]}T{slot["time"]}' not in previous_slots
        ]
        if new_slots:
            lines = ["U-Fly 60 出现可预订时段（Wanaka／新西兰当地时间）："]
            lines.extend(
                f'• {slot["day"]} {display_time(slot["time"])}'
                for slot in new_slots
            )
            lines.append("请尽快打开预订页面，余位可能随时变化。")
            send_ntfy(
                "U-Fly 60 有余位！",
                "\n".join(lines),
                booking_url(new_slots[0]["day"]),
            )

        next_state = {"slots": sorted(current_keys), "errorNotified": False}
        if next_state != previous:
            save_state(issue_number, next_state)
        print(json.dumps({"ok": True, "slots": len(current)}))
        return 0
    except Exception as error:
        print(f"Check failed: {error}", file=sys.stderr)
        if not previous.get("errorNotified", False):
            send_ntfy(
                "U-Fly 监测暂时出错",
                f"GitHub 云端监测器无法完成检查：{error}",
                booking_url(DATES[0]),
            )
            save_state(
                issue_number,
                {"slots": sorted(previous_slots), "errorNotified": True},
            )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
