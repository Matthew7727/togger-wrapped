#!/usr/bin/env python3
"""Generate wrapped analysis JSON from a WhatsApp export zip."""

from __future__ import annotations

import argparse
import json
import re
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path


LINE_RE = re.compile(
    r"^\[(\d{2}/\d{2}/\d{4}),\s(\d{1,2}:\d{2}:\d{2})\]\s([^:]+):\s?(.*)$"
)


@dataclass
class Message:
    dt: datetime
    sender: str
    text: str


def parse_messages(zip_path: Path, chat_file: str) -> list[Message]:
    with zipfile.ZipFile(zip_path) as zf:
        lines = zf.read(chat_file).decode("utf-8", errors="replace").splitlines()

    messages: list[Message] = []
    current: Message | None = None

    for line in lines:
        clean = line.lstrip("\u200e\u200f")
        match = LINE_RE.match(clean)
        if match:
            date_str, time_str, sender, text = match.groups()
            dt = datetime.strptime(f"{date_str} {time_str}", "%d/%m/%Y %H:%M:%S")
            current = Message(dt=dt, sender=sender.strip(), text=text)
            messages.append(current)
        elif current is not None:
            current.text += "\n" + clean

    return messages


def short_name(full: str) -> str:
    return full.split(" ")[0]


def build_summary(
    messages: list[Message],
    season_start: datetime,
    season_end: datetime,
    group_sender: str,
) -> dict:
    msgs = [
        m
        for m in messages
        if season_start <= m.dt < season_end and m.sender != group_sender
    ]

    month_counts = Counter(m.dt.strftime("%Y-%m") for m in msgs)

    starts = Counter()
    for idx, msg in enumerate(msgs):
        if idx == 0 or (msg.dt - msgs[idx - 1].dt).total_seconds() >= 7200:
            starts[msg.sender] += 1

    handoffs = Counter()
    for a, b in zip(msgs, msgs[1:]):
        if a.sender != b.sender:
            handoffs[(a.sender, b.sender)] += 1

    question_stats: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for idx, msg in enumerate(msgs):
        if "?" not in msg.text:
            continue
        question_stats[msg.sender][0] += 1
        for next_msg in msgs[idx + 1 :]:
            if next_msg.sender == msg.sender:
                continue
            if (next_msg.dt - msg.dt) > timedelta(minutes=30):
                break
            question_stats[msg.sender][1] += 1
            break

    night_owls = Counter(m.sender for m in msgs if 0 <= m.dt.hour <= 5)

    first_message_by_day: dict = {}
    for msg in msgs:
        day = msg.dt.date()
        if day not in first_message_by_day:
            first_message_by_day[day] = msg.sender
    day_starters = Counter(first_message_by_day.values())

    question_conversion = []
    for sender, (total, answered) in question_stats.items():
        if total < 5:
            continue
        question_conversion.append(
            {
                "name": short_name(sender),
                "answered": answered,
                "total": total,
                "rate": round(100 * answered / total),
            }
        )
    question_conversion.sort(
        key=lambda row: (row["rate"], row["answered"], row["total"]), reverse=True
    )

    return {
        "season": {
            "start": season_start.strftime("%Y-%m-%d"),
            "end": (season_end - timedelta(days=1)).strftime("%Y-%m-%d"),
        },
        "methodology": {
            "conversation_gap_minutes": 120,
            "question_answer_window_minutes": 30,
            "night_owl_hours": "00:00-05:59",
            "notes": "Filtered to user messages only (excludes system posts by group sender).",
        },
        "new_metrics": {
            "monthly_momentum": [
                {"month": month, "messages": count}
                for month, count in month_counts.most_common(6)
            ],
            "conversation_starts": [
                {"name": short_name(sender), "count": count}
                for sender, count in starts.most_common(5)
            ],
            "top_handoffs": [
                {"from": short_name(src), "to": short_name(dst), "count": count}
                for (src, dst), count in handoffs.most_common(5)
            ],
            "question_conversion": question_conversion[:5],
            "night_owls": [
                {"name": short_name(sender), "count": count}
                for sender, count in night_owls.most_common(5)
            ],
            "day_starters": [
                {"name": short_name(sender), "count": count}
                for sender, count in day_starters.most_common(5)
            ],
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--zip", required=True, help="Path to WhatsApp export zip")
    parser.add_argument("--output", required=True, help="Output JSON file path")
    parser.add_argument("--chat-file", default="_chat.txt", help="Chat file in zip")
    parser.add_argument("--group-sender", default="Joe's BBQ Togger")
    parser.add_argument("--start", default="2025-03-31", help="Season start (YYYY-MM-DD)")
    parser.add_argument(
        "--end-exclusive",
        default="2026-07-05",
        help="Season end exclusive (YYYY-MM-DD)",
    )
    args = parser.parse_args()

    start = datetime.strptime(args.start, "%Y-%m-%d")
    end = datetime.strptime(args.end_exclusive, "%Y-%m-%d")

    messages = parse_messages(Path(args.zip), args.chat_file)
    summary = build_summary(messages, start, end, args.group_sender)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
