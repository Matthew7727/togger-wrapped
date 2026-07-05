#!/usr/bin/env python3
"""Generate the full Togger Wrapped analysis JSON from a WhatsApp export zip.

Produces data/summary.json, consumed by almanac.html (the deep-dive site).
Everything is static and reproducible: re-run after dropping in a fresh export.
"""

from __future__ import annotations

import argparse
import json
import re
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

LINE_RE = re.compile(
    r"^\[(\d{2}/\d{2}/\d{4}),\s(\d{1,2}:\d{2}:\d{2})\]\s([^:]+):\s?(.*)$"
)

# Emoji detection (broad ranges). Skin-tone modifiers / variation selectors are
# stripped when choosing a "signature" emoji so 🏻 doesn't win.
EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001FAFF"
    "\U00002600-\U000027BF"
    "\U0001F1E6-\U0001F1FF"
    "\U00002190-\U000021FF"
    "\U00002B00-\U00002BFF"
    "\U0001F000-\U0001F0FF"
    "]",
    flags=re.UNICODE,
)
SKIN_TONES = {"\U0001F3FB", "\U0001F3FC", "\U0001F3FD", "\U0001F3FE", "\U0001F3FF"}
IGNORE_EMOJI = SKIN_TONES | {"\uFE0F", "\u200D"}

SWEARS = [
    "shite",
    "fucking",
    "fuck",
    "shit",
    "bastard",
    "bollocks",
    "wanker",
    "twat",
    "prick",
    "arse",
    "bellend",
    "knobhead",
]

# Signature vocabulary tracked for the dictionary section.
DICTIONARY_TERMS = [
    "youse",
    "yous",
    "goanna",
    "gucci",
    "lads",
    "footy",
    "grub",
    "mert",
    "cheeky",
    "sound",
]

# Chat sender -> short display name used across the site.
DISPLAY_NAMES = {
    "James Reid": "James R",
    "Jack Flarty": "Jack",
    "Matt Eccleston": "Matt",
    "Charlie Corfield": "Charlie",
    "Curtis": "Curtis",
    "Michael Baker": "Michael",
    "Joseph Kilcullen": "Joseph",
    "Lewis Moran": "Lewis",
    "Tom Longworth": "Tom",
    "Edward Moran (jacks Friend)": "Edward",
    "Aaron Reid": "Aaron",
    "Jamie Dahl": "Jamie",
    "James Fleming": "James F",
    "Joe Allen": "Joe A",
    "Joe Tom Friend": "Joe T",
    "James Hynes": "James H",
    "Tom Moss (Jacks Friend)": "Tom M",
    "~\u202fAlex": "Alex",
    "~\u202fChris Kennedy": "Chris",
}


@dataclass
class Message:
    dt: datetime
    sender: str
    text: str


@dataclass
class PlayerStats:
    full: str
    display: str
    messages: int = 0
    words: int = 0
    photo: int = 0
    gif: int = 0
    video: int = 0
    sticker: int = 0
    audio: int = 0
    doc: int = 0
    media: int = 0
    polls: int = 0
    questions: int = 0
    questions_answered: int = 0
    deleted: int = 0
    edited: int = 0
    night: int = 0
    emoji: int = 0
    swears: int = 0
    conv_starts: int = 0
    day_starts: int = 0
    last_words: int = 0
    reply_waits: list = field(default_factory=list)
    emoji_counter: Counter = field(default_factory=Counter)
    longest_message: int = 0


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


def display_name(full: str) -> str:
    return DISPLAY_NAMES.get(full, full.split(" ")[0])


def media_type(text: str) -> str | None:
    if "PHOTO-" in text:
        return "photo"
    if "GIF-" in text:
        return "gif"
    if "VIDEO-" in text:
        return "video"
    if "STICKER-" in text:
        return "sticker"
    if "AUDIO-" in text:
        return "audio"
    if "<attached:" in text:
        return "doc"
    return None


def signature_emoji(counter: Counter) -> str:
    for emoji, _ in counter.most_common():
        if emoji not in IGNORE_EMOJI:
            return emoji
    return ""


def median(values: list[float]) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    n = len(values)
    mid = n // 2
    return values[mid] if n % 2 else (values[mid - 1] + values[mid]) / 2


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

    players: dict[str, PlayerStats] = {}

    def player(sender: str) -> PlayerStats:
        if sender not in players:
            players[sender] = PlayerStats(full=sender, display=display_name(sender))
        return players[sender]

    month_counts: Counter = Counter()
    heat = [[0] * 24 for _ in range(7)]  # [weekday][hour], Monday=0
    handoffs: Counter = Counter()
    dictionary: dict[str, Counter] = {term: Counter() for term in DICTIONARY_TERMS}
    days_seen: set = set()
    first_of_day: dict = {}
    day_counts: Counter = Counter()

    longest_message = {"name": "", "chars": 0, "preview": ""}
    biggest_photo_run = {"name": "", "count": 0, "date": ""}
    run_sender = None
    run_len = 0
    run_start_date = ""

    for i, m in enumerate(msgs):
        p = player(m.sender)
        p.messages += 1
        month_counts[m.dt.strftime("%Y-%m")] += 1
        heat[m.dt.weekday()][m.dt.hour] += 1
        day = m.dt.date()
        day_counts[day] += 1
        days_seen.add(day)
        if day not in first_of_day:
            first_of_day[day] = m.sender
            player(m.sender).day_starts += 1

        text = m.text

        if "This message was deleted" in text:
            p.deleted += 1
            continue
        if "This message was edited" in text:
            p.edited += 1

        mtype = media_type(text)
        if mtype:
            setattr(p, mtype, getattr(p, mtype) + 1)
            p.media += 1

        # photo-run record (consecutive photos by same sender)
        if mtype == "photo":
            if m.sender == run_sender:
                run_len += 1
            else:
                run_sender = m.sender
                run_len = 1
                run_start_date = m.dt.strftime("%d %b %Y")
            if run_len > biggest_photo_run["count"]:
                biggest_photo_run = {
                    "name": display_name(m.sender),
                    "count": run_len,
                    "date": run_start_date,
                }
        else:
            run_sender = None
            run_len = 0

        if "POLL:" in text:
            p.polls += 1
        if "?" in text:
            p.questions += 1
            sender = m.sender
            for nxt in msgs[i + 1 :]:
                if nxt.sender == sender:
                    continue
                if (nxt.dt - m.dt) > timedelta(minutes=30):
                    break
                p.questions_answered += 1
                break

        clean = re.sub(r"<attached:[^>]+>", "", text)
        word_count = len(clean.split())
        p.words += word_count

        char_len = len(clean.strip())
        if char_len > p.longest_message:
            p.longest_message = char_len
        if char_len > longest_message["chars"]:
            longest_message = {
                "name": display_name(m.sender),
                "chars": char_len,
                "preview": clean.strip()[:140],
            }

        for emoji in EMOJI_RE.findall(text):
            p.emoji_counter[emoji] += 1
            if emoji not in IGNORE_EMOJI:
                p.emoji += 1

        if 0 <= m.dt.hour <= 5:
            p.night += 1

        lower = text.lower()
        for swear in SWEARS:
            p.swears += len(re.findall(r"\b" + re.escape(swear) + r"\b", lower))
        for term in DICTIONARY_TERMS:
            hits = len(re.findall(r"\b" + re.escape(term) + r"\b", lower))
            if hits:
                dictionary[term][m.sender] += hits

    # conversation starts, last words, reply latency
    for i, m in enumerate(msgs):
        prev_gap = None if i == 0 else (m.dt - msgs[i - 1].dt).total_seconds()
        if i == 0 or prev_gap >= 7200:
            player(m.sender).conv_starts += 1
        if i > 0 and msgs[i - 1].sender != m.sender and prev_gap is not None:
            player(m.sender).reply_waits.append(prev_gap)
        next_gap = (
            None if i == len(msgs) - 1 else (msgs[i + 1].dt - m.dt).total_seconds()
        )
        if i == len(msgs) - 1 or next_gap >= 7200:
            player(m.sender).last_words += 1
        if i < len(msgs) - 1 and msgs[i + 1].sender != m.sender:
            handoffs[(m.sender, msgs[i + 1].sender)] += 1

    # longest silence + streak
    longest_silence = {"days": 0.0, "from": "", "to": "", "breaker": ""}
    for a, b in zip(msgs, msgs[1:]):
        gap = (b.dt - a.dt).total_seconds() / 86400
        if gap > longest_silence["days"]:
            longest_silence = {
                "days": round(gap, 1),
                "from": a.dt.strftime("%d %b %Y"),
                "to": b.dt.strftime("%d %b %Y"),
                "breaker": display_name(b.sender),
            }

    sorted_days = sorted(days_seen)
    longest_streak = 0
    streak = 0
    prev_day = None
    for day in sorted_days:
        if prev_day is not None and (day - prev_day).days == 1:
            streak += 1
        else:
            streak = 1
        longest_streak = max(longest_streak, streak)
        prev_day = day

    biggest_day = max(day_counts.items(), key=lambda kv: kv[1])

    # ---- assemble player list ----
    def player_dict(p: PlayerStats, rank: int) -> dict:
        active = max(1, p.messages - p.deleted)
        return {
            "rank": rank,
            "name": p.display,
            "full": p.full,
            "messages": p.messages,
            "words": p.words,
            "wpm": round(p.words / active, 1),
            "photo": p.photo,
            "gif": p.gif,
            "video": p.video,
            "sticker": p.sticker,
            "audio": p.audio,
            "doc": p.doc,
            "media": p.media,
            "polls": p.polls,
            "questions": p.questions,
            "questions_answered": p.questions_answered,
            "deleted": p.deleted,
            "edited": p.edited,
            "night": p.night,
            "emoji": p.emoji,
            "top_emoji": signature_emoji(p.emoji_counter),
            "swears": p.swears,
            "conv_starts": p.conv_starts,
            "day_starts": p.day_starts,
            "last_words": p.last_words,
            "longest_message": p.longest_message,
            "median_reply_s": int(median(p.reply_waits)),
        }

    ordered = sorted(players.values(), key=lambda p: p.messages, reverse=True)
    player_rows = [player_dict(p, idx + 1) for idx, p in enumerate(ordered)]

    def top(rows, key, count=None, reverse=True, min_msgs=0):
        pool = [r for r in rows if r["messages"] >= min_msgs]
        result = sorted(pool, key=lambda r: r[key], reverse=reverse)
        return result if count is None else result[:count]

    def leaderboard(rows, value_key, label, count=8, reverse=True, min_msgs=0):
        picked = top(rows, value_key, count, reverse, min_msgs)
        return [
            {"name": r["name"], "value": r[value_key], "label": label} for r in picked
        ]

    question_rows = [
        {
            "name": r["name"],
            "answered": r["questions_answered"],
            "total": r["questions"],
            "rate": round(100 * r["questions_answered"] / r["questions"]),
        }
        for r in player_rows
        if r["questions"] >= 10
    ]
    question_rows.sort(key=lambda r: (r["rate"], r["answered"]), reverse=True)

    reply_rows = [
        {"name": r["name"], "value": r["median_reply_s"]}
        for r in player_rows
        if r["median_reply_s"] > 0 and r["messages"] >= 30
    ]
    reply_rows.sort(key=lambda r: r["value"])

    total_words = sum(p.words for p in players.values())
    total_media = sum(p.media for p in players.values())
    total_polls = sum(p.polls for p in players.values())
    total_edited = sum(p.edited for p in players.values())
    total_deleted = sum(p.deleted for p in players.values())

    return {
        "meta": {
            "generated": datetime.utcnow().strftime("%Y-%m-%d"),
            "season": {
                "start": season_start.strftime("%Y-%m-%d"),
                "end": (season_end - timedelta(days=1)).strftime("%Y-%m-%d"),
                "days_active": len(days_seen),
                "days_total": (season_end - season_start).days,
            },
            "totals": {
                "messages": len(msgs),
                "words": total_words,
                "media": total_media,
                "polls": total_polls,
                "edited": total_edited,
                "deleted": total_deleted,
                "participants": len(players),
            },
        },
        "methodology": {
            "conversation_gap_minutes": 120,
            "question_answer_window_minutes": 30,
            "night_hours": "00:00-05:59",
            "notes": (
                "Parsed from _chat.txt. System posts excluded. A conversation "
                "start is the first message after a 2h+ silence; last words are "
                "messages before a 2h+ silence. Reply time is the median gap "
                "before a person replies to someone else. Media types read from "
                "attachment filenames (PHOTO/GIF/VIDEO/STICKER/AUDIO)."
            ),
        },
        "players": player_rows,
        "leaderboards": {
            "messages": leaderboard(player_rows, "messages", "messages"),
            "words": leaderboard(player_rows, "words", "words"),
            "media": leaderboard(player_rows, "media", "media"),
            "polls": leaderboard(player_rows, "polls", "polls"),
            "gifs": leaderboard(player_rows, "gif", "GIFs"),
            "emoji": leaderboard(player_rows, "emoji", "emoji"),
            "swears": leaderboard(player_rows, "swears", "swears"),
            "night_owls": leaderboard(player_rows, "night", "night msgs"),
            "day_starters": leaderboard(player_rows, "day_starts", "days opened"),
            "conv_starts": leaderboard(player_rows, "conv_starts", "convos started"),
            "wpm": leaderboard(player_rows, "wpm", "words/msg", min_msgs=30),
            "fastest_reply": [
                {"name": r["name"], "value": r["value"], "label": "sec median"}
                for r in reply_rows[:8]
            ],
            "question_conversion": question_rows[:8],
        },
        "monthly": [
            {"month": month, "messages": month_counts[month]}
            for month in sorted(month_counts)
        ],
        "heatmap": {
            "weekdays": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
            "grid": heat,
            "max": max(max(row) for row in heat),
        },
        "handoffs": [
            {"from": display_name(a), "to": display_name(b), "count": c}
            for (a, b), c in handoffs.most_common(12)
        ],
        "records": {
            "longest_message": longest_message,
            "longest_silence": longest_silence,
            "longest_streak_days": longest_streak,
            "biggest_day": {
                "date": biggest_day[0].strftime("%d %b %Y"),
                "count": biggest_day[1],
            },
            "biggest_photo_run": biggest_photo_run,
        },
        "dictionary": [
            {
                "word": term,
                "count": sum(dictionary[term].values()),
                "owner": display_name(dictionary[term].most_common(1)[0][0])
                if dictionary[term]
                else "",
            }
            for term in DICTIONARY_TERMS
            if sum(dictionary[term].values()) > 0
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--zip", required=True, help="Path to WhatsApp export zip")
    parser.add_argument("--output", required=True, help="Output JSON file path")
    parser.add_argument("--chat-file", default="_chat.txt", help="Chat file in zip")
    parser.add_argument("--group-sender", default="Joe's BBQ Togger")
    parser.add_argument("--start", default="2025-03-31", help="Season start YYYY-MM-DD")
    parser.add_argument(
        "--end-exclusive", default="2026-07-05", help="Season end exclusive YYYY-MM-DD"
    )
    args = parser.parse_args()

    start = datetime.strptime(args.start, "%Y-%m-%d")
    end = datetime.strptime(args.end_exclusive, "%Y-%m-%d")

    messages = parse_messages(Path(args.zip), args.chat_file)
    summary = build_summary(messages, start, end, args.group_sender)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {out_path} ({len(summary['players'])} players)")


if __name__ == "__main__":
    main()
