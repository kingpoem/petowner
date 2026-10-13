"""房态呼吸：把护理师写下的话读成节奏，再铺成一张会起伏的平面图。

不调用外部模型。词表和冷静值是这套店自己的语法，同样一句话永远得到同样的呼吸。
"""

from dataclasses import dataclass

MARKS = (
    ("eat", "进食", ("喂", "吃", "餐", "粮", "饮", "冻干")),
    ("walk", "遛弯", ("遛", "散步", "草坪")),
    ("groom", "洗护", ("洗", "梳", "吹", "猫砂", "指甲")),
    ("sun", "日照", ("晒", "窗台")),
    ("play", "玩耍", ("玩", "开心")),
    ("rest", "安睡", ("休息", "睡觉", "午休")),
    ("meds", "用药", ("药",)),
)

WINGS = (("dog", "狗狗区"), ("any", "家庭区"), ("cat", "猫咪区"))
SIZE = {"standard": 118, "deluxe": 132, "suite": 148}
PITCH_X = 176
PITCH_Y = 176
WING_SPAN = 380


@dataclass(frozen=True)
class Reading:
    labels: tuple[str, ...]
    calm: int
    breath: float
    caption: str


def breathe(text: str, *, alert: bool = False) -> Reading:
    blob = text or ""
    found = tuple(mark for mark in MARKS if any(word in blob for word in mark[2]))
    calm = 68
    if any(mark[0] == "eat" for mark in found) and "未进食" not in blob and "拒食" not in blob:
        calm += 10
    if any(mark[0] in {"sun", "rest"} for mark in found):
        calm += 8
    if any(mark[0] == "play" for mark in found):
        calm += 4
    if any(phrase in blob for phrase in ("未进食", "拒食", "只吃一半", "只吃了一半")):
        calm -= 18
    if alert:
        calm -= 36
    calm = max(8, min(96, calm))
    breath = round(1.15 + calm / 100 * 4.1, 2)
    labels = tuple(mark[1] for mark in found)
    if labels and alert:
        caption = "需要看护 · " + " · ".join(labels)
    elif labels:
        caption = " · ".join(labels)
    elif alert:
        caption = "需要看护"
    else:
        caption = "安稳"
    return Reading(labels, calm, breath, caption)


def quiet_index(calm_values: list[int], occupied: int) -> int:
    if occupied <= 0 or not calm_values:
        return 100
    return round(sum(calm_values) / len(calm_values))


def quiet_line(score: int, occupied: int) -> str:
    if occupied <= 0:
        return "店里很静，房间刚收拾好"
    if score >= 85:
        return "整店像午睡"
    if score >= 65:
        return "节奏平稳"
    if score >= 40:
        return "有点热闹"
    return "护理师在加紧看护"


def _clip(text: str, limit: int) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _short_caption(caption: str) -> str:
    parts = [part for part in (caption or "").split(" · ") if part]
    if len(parts) <= 2:
        return " · ".join(parts)
    return f"{parts[0]} · {parts[1]}"


def fold_clock(events: list[dict], hours: range | tuple = range(7, 22)) -> dict:
    """把多天的护理记录按钟点叠回同一天。

    某个钟点只看「时刻不晚于它」的记录，同一房间取最近一次。
    早上还看不到傍晚的洗澡，拖到晚上才会换成洗护。
    """
    frames = {}
    for hour in hours:
        cutoff = hour * 60 + 59
        latest: dict = {}
        for event in events:
            if event["minute"] > cutoff:
                continue
            current = latest.get(event["room_id"])
            if current is None or event["stamp"] >= current["stamp"]:
                latest[event["room_id"]] = event
        frame = {}
        for room_id, event in latest.items():
            reading = breathe(event["text"], alert=event["alert"])
            frame[str(room_id)] = {
                "breath": reading.breath,
                "caption": _short_caption(reading.caption),
                "alert": bool(event["alert"]),
            }
        frames[str(hour)] = frame
    return frames


@dataclass(frozen=True)
class Thread:
    label: str
    tone: str


@dataclass(frozen=True)
class Weave:
    score: int
    line: str
    threads: tuple[Thread, ...]


_SPECIES = {"dog": "狗", "cat": "猫", "other": "宠物"}
_TEMPER = {"gentle": "温顺", "active": "活泼", "timid": "胆小", "aggressive": "有攻击性"}


def weave(species: str, temperament: str, neighbors: list[tuple[str, str]]) -> Weave:
    """入住织体：只看物种和性格，不看别人的名字。"""
    if not neighbors:
        return Weave(92, "这几天这侧很安静，TA 会自己待着", ())
    score = 78
    threads = []
    for other_species, other_temper in neighbors:
        label = f"{_TEMPER.get(other_temper, '性格未知')}的{_SPECIES.get(other_species, '宠物')}"
        if temperament == "aggressive" or other_temper == "aggressive":
            tone = "watch"
            score -= 22
        elif species == "dog" and other_species == "cat" and other_temper == "timid":
            tone = "watch"
            score -= 14
        elif species == other_species and {temperament, other_temper} <= {"gentle", "timid"}:
            tone = "kin"
            score += 6
        elif species != other_species:
            tone = "calm"
            score += 2
        else:
            tone = "kin"
            score += 3
        threads.append(Thread(label, tone))
    score = max(8, min(96, score))
    if score >= 80:
        line = "和店里的住客合得来"
    elif score >= 55:
        line = "分区之后可以平安相处"
    else:
        line = "建议错开，或选独立套房"
    return Weave(score, line, tuple(threads))


def layout_atlas(rooms, guests: dict) -> dict:
    """按狗区、家庭区、猫区从左到右铺房间。客人字典的键是房间主键。"""
    grouped: dict[str, list] = {key: [] for key, _label in WINGS}
    for room in rooms:
        grouped.setdefault(room.pet_type, []).append(room)
    cells = []
    wings = []
    max_x, max_y = 240, 200
    slot = 0
    for key, label in WINGS:
        group = grouped.get(key) or []
        if not group:
            continue
        base_x = 28 + slot * WING_SPAN
        wings.append({"key": key, "label": label, "x": base_x})
        for index, room in enumerate(group):
            size = SIZE.get(room.room_type, 118)
            x = base_x + (index % 2) * PITCH_X
            y = 52 + (index // 2) * PITCH_Y
            guest = guests.get(room.pk)
            cells.append(
                {
                    "room_id": room.pk,
                    "x": x,
                    "y": y,
                    "size": size,
                    "cx": x + size / 2,
                    "name_y": y + size * 0.42,
                    "caption_y": y + size * 0.62,
                    "meta_y": y + size - 18,
                    "name": _clip(guest["name"], 6) if guest else "空房",
                    "caption": _short_caption(guest["caption"]) if guest else _clip(room.display_name, 8),
                    "meta": room.number if guest else "",
                    "breath": guest["breath"] if guest else 0,
                    "alert": bool(guest and guest["alert"]),
                    "live": guest is not None,
                    "wing": key,
                }
            )
            max_x = max(max_x, x + size)
            max_y = max(max_y, y + size)
        slot += 1
    return {"width": int(max_x + 40), "height": int(max_y + 36), "cells": cells, "wings": wings}
