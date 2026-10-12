#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["pypinyin==0.55.0"]
# ///
"""中英混读、中文校对、阅读稿与火山 TTS / 情绪演绎；preview/prepare/dry-run 均不访问网络。"""
import argparse
import base64
import hashlib
import html
import io
import json
import math
import os
import re
import shutil
import struct
import sys
from datetime import datetime, timedelta, timezone
import time
import urllib.error
import urllib.request
import uuid
import wave
from pathlib import Path

from pypinyin import Style, lazy_pinyin, pinyin
from pypinyin.contrib.tone_convert import to_tone, to_normal
from pypinyin.constants import PINYIN_DICT

ENDPOINT = "https://openspeech.bytedance.com/api/v3/tts/unidirectional"
PERFORM_ENDPOINT = "https://openspeech.bytedance.com/api/v3/tts/create"
PERFORM_MODEL = "seed-audio-1.0"
VOICE = "zh_female_vv_uranus_bigtts"
PRONUNCIATIONS = Path(__file__).resolve().parents[1] / "references/pronunciations.json"
DIGITS = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine")
PCM_CHUNK_FRAMES = 24000
DIALECTS = {"beijing": "北京话", "dongbei": "东北话", "henan": "河南话", "shaanxi": "陕西话",
            "shanghai": "上海话", "sichuan": "四川话", "tianjin": "天津话", "yue": "粤语"}
HAN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\U00020000-\U000323af]")
SYLLABLES = {to_normal(sound) for sounds in PINYIN_DICT.values() for sound in sounds.split(",")}


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def check_text(text):
    if not isinstance(text, str) or not (HAN.search(text) or re.search(r"[A-Za-z0-9]", text)):
        raise ValueError("文本须包含中文、英文或数字")
    if any(c.isalpha() and not (HAN.fullmatch(c) or re.fullmatch(r"[A-Za-z]", c)) for c in text):
        raise ValueError("当前支持中文与英文；其他语言须先核实音色能力")


def sentence_ends(text):
    ends = []
    for match in re.finditer(r'[。！？!?]+["”’」』）】]*|\n+|\.+["”’」』）】]*', text):
        if match.group().startswith("."):
            # 小数、型号、URL 和常见缩写内部的点不是句末；英文句末须有空白或 EOF。
            if match.end() < len(text) and not text[match.end()].isspace():
                continue
            before = text[:match.start()]
            word = re.search(r"[A-Za-z.]+$", before)
            if word and (word.group().lower() in {"mr", "mrs", "ms", "dr", "prof", "vs", "etc", "e.g", "i.e"}
                         or re.fullmatch(r"(?:[A-Za-z]\.)*[A-Za-z]", word.group())):
                continue
        ends.append(match.end())
    if not ends or ends[-1] != len(text):
        ends.append(len(text))
    return ends


def scan(text):
    suggested = lazy_pinyin(text, style=Style.TONE3, neutral_tone_with_five=True,
                            errors=lambda s: list(s))
    if len(suggested) != len(text):
        raise ValueError("拼音位置无法与原文对齐，请检查特殊字符")
    rows = []
    for i, char in enumerate(text):
        if not HAN.fullmatch(char):
            continue
        choices = pinyin(char, style=Style.TONE3, heteronym=True,
                         neutral_tone_with_five=True)[0]
        if len(choices) > 1:
            rows.append({"start": i, "text": char, "pinyin": [suggested[i]],
                         "status": "pending", "delivery": "native", "note": "词典建议，待语境校对"})
    return rows


def validate_pronunciations(table):
    if table is None:
        return
    if (not isinstance(table, dict) or set(table) != {"version", "words", "acronyms", "models", "decimal_point"}
            or type(table["version"]) is not int or table["version"] != 1):
        raise ValueError("发音表须包含 version=1、words、acronyms、models、decimal_point")
    if not isinstance(table["words"], dict) or not isinstance(table["acronyms"], dict):
        raise ValueError("words 与 acronyms 须为对象")
    for word, hint in table["words"].items():
        if not isinstance(word, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,127}", word):
            raise ValueError("英语提示词须为不含空格的英文词或型号")
        if hint is not None and (not isinstance(hint, str) or not 1 <= len(hint) <= 200
                                or not re.fullmatch(r"[ -~]+", hint) or not re.search(r"[A-Za-z]", hint)):
            raise ValueError("英语读音提示须为英文字符串或 null（原生读法），不使用中文音译")
    for word, target in table["acronyms"].items():
        if not isinstance(word, str) or not re.fullmatch(r"[A-Z][A-Z0-9-]{0,8}", word):
            raise ValueError("缩写原词须为 1～9 个大写英文、数字或短横线字符")
        if (not isinstance(target, str) or not 1 <= len(target) <= 500
                or not re.fullmatch(r"[A-Za-z0-9 .'-]+", target) or not re.search(r"[A-Za-z]", target)):
            raise ValueError("缩写目标须为英文逐字母读法，不使用中文音译")
    models = table["models"]
    if not isinstance(models, list) or any(not isinstance(word, str) or not 1 <= len(word) <= 9
            or not re.fullmatch(r"[Vv]?[0-9]+(?:\.[0-9]+)+", word) for word in models):
        raise ValueError("models 须为最多 9 字符的点分数字型号数组，可带 V/v 前缀")
    if len(set(models)) != len(models):
        raise ValueError("型号不可重复")
    if set(table["words"]) & (set(table["acronyms"]) | set(models)):
        raise ValueError("同词不能同时设置英语提示和缩写/型号转写")
    if table["decimal_point"] not in ("point", "点"):
        raise ValueError("decimal_point 只能为 point 或 点")
    if len(table["words"]) + len(table["acronyms"]) + len(models) > 5000:
        raise ValueError("发音表最多 5000 项")


def token_starts(text, word, model=False):
    boundary = r"[A-Za-z0-9_.]" if model else r"[A-Za-z0-9_]"
    return {match.start() for match in re.finditer(
        rf"(?<!{boundary}){re.escape(word)}(?!{boundary})", text)}


def english_integer(digits):
    if len(digits) > 1 and digits.startswith("0"):
        return " ".join(DIGITS[int(digit)] for digit in digits)
    number = int(digits)
    small = DIGITS + ("ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
                      "sixteen", "seventeen", "eighteen", "nineteen")
    if number < 20:
        return small[number]
    if number < 100:
        tens, rest = divmod(number, 10)
        return ("twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety")[tens - 2] + (
            " " + small[rest] if rest else "")
    for divisor, label in ((1000000, "million"), (1000, "thousand"), (100, "hundred")):
        if number >= divisor:
            first, rest = divmod(number, divisor)
            return english_integer(str(first)) + " " + label + (" " + english_integer(str(rest)) if rest else "")


def table_controls(clip, table):
    validate_pronunciations(table)
    rules, instructions, intended = {}, [], {}
    if table is None:
        return rules, instructions, intended
    text = clip["text"]
    for word, hint in sorted(table["words"].items()):
        if hint is not None and token_starts(text, word):
            instructions.append(f'英文词“{word}”按英语读作 {hint}，不要读成中文音译。')
    targets = dict(table["acronyms"])
    for model in table["models"]:
        parts = model.lstrip("Vv").split(".")
        if table["decimal_point"] == "point":
            spoken = " point ".join([english_integer(parts[0])] + [
                " ".join(DIGITS[int(digit)] for digit in part) for part in parts[1:]])
        else:
            spoken = "点".join(parts)
        targets[model] = (model[0] + " " if model[0] in "Vv" else "") + spoken
    for word, target in sorted(targets.items()):
        starts = token_starts(text, word, word in table["models"])
        if starts:
            rules[word], intended[word] = target, starts
    if any(word in rules for word in table["acronyms"]):
        instructions.append("缩写按英文逐个字母读，保留字母与数字之间的自然衔接。")
    return rules, instructions, intended


def check_table_matches(text, rules, intended):
    if not intended:
        return
    matched, i = {word: set() for word in intended}, 0
    while i < len(text):
        matches = [word for word in rules if text.startswith(word, i)]
        if not matches:
            i += 1
            continue
        word = max(matches, key=len)
        if word in intended:
            if i not in intended[word]:
                raise ValueError(f"发音规则 {word} 会误改另一词或型号的子串；明确完整词组或拆段")
            matched[word].add(i)
        i += len(word)
    if matched != intended:
        raise ValueError("更长发音字典规则覆盖了混读规则；明确完整词组或拆段")


def readings(clip, complete=False, pronunciation_table=None):
    text = clip["text"]
    occupied, reviewed, expected, rules = set(), set(), {}, {}
    rows = sorted(clip.get("readings", []), key=lambda r: r["start"])
    for row in rows:
        start, word, sounds = row["start"], row["text"], row["pinyin"]
        if type(start) is not int or start < 0 or not isinstance(word, str) or not 1 <= len(word) <= 9:
            raise ValueError("标注位置或词组长度无效")
        if not all(HAN.fullmatch(c) for c in word) or text[start:start + len(word)] != word:
            raise ValueError(f"标注与原文不符：{word}")
        if not isinstance(sounds, list) or len(sounds) != len(word) or any(
                not isinstance(s, str) or not re.fullmatch(r"[a-zv]+[1-5]", s)
                or to_normal(s) not in SYLLABLES for s in sounds):
            raise ValueError(f"每个字须有一个数字声调拼音：{word}")
        positions = set(range(start, start + len(word)))
        if positions & occupied:
            raise ValueError(f"标注重叠：{word}")
        occupied |= positions
        if row.get("status") not in ("pending", "reviewed"):
            raise ValueError("status 只能为 pending 或 reviewed")
        delivery = row.get("delivery", "spoken_alias" if "spoken_alias" in row else "dictionary")
        if delivery not in ("native", "dictionary", "instruction", "spoken_alias"):
            raise ValueError("未知读音投递方式")
        if delivery == "spoken_alias":
            alias = row.get("spoken_alias")
            # ponytail: 别名限等长汉字，避免维护第二套位置映射；不同长度时显式拆段。
            if not isinstance(alias, str) or len(alias) != len(word) or not all(HAN.fullmatch(c) for c in alias):
                raise ValueError("可听别名须为与原词等长的汉字")
            for char, sound in zip(alias, sounds):
                choices = pinyin(char, style=Style.TONE3, heteronym=True, neutral_tone_with_five=True)[0]
                if choices != [sound]:
                    raise ValueError(f"别名字典读音不唯一或与指定读音不符：{char}")
            if row["status"] == "reviewed" and row.get("alias_approved") is not True:
                raise ValueError("可听替换须有明确授权记录 alias_approved=true")
        elif "spoken_alias" in row:
            raise ValueError("spoken_alias 与 delivery 不一致")
        if row["status"] != "reviewed":
            if complete:
                raise ValueError(f"尚未校对：{word}")
            continue
        reviewed |= positions
        if delivery != "dictionary":
            continue
        expected.update(zip(range(start, start + len(word)), sounds))
        if word in rules and rules[word] != sounds:
            raise ValueError(f"同词不同读音：{word}；使用明确词组或拆段")
        rules[word] = sounds
    dictionary = clip.get("pronunciation_dict", {"tone": []})
    if not isinstance(dictionary, dict) or set(dictionary) != {"tone"} or not isinstance(dictionary["tone"], list):
        raise ValueError("pronunciation_dict 必须为包含 tone 数组的对象")
    seen = set()
    for entry in dictionary["tone"]:
        if not isinstance(entry, str) or entry.count("/") != 1:
            raise ValueError("发音字典规则须为 原词/修正内容")
        word, target = entry.split("/")
        if not 1 <= len(word) <= 9 or any(c.isspace() for c in word) or word in seen:
            raise ValueError("字典原词须为 1～9 字符、不含空格，且不可重复")
        check_text(word)
        seen.add(word)
        if target.startswith("("):
            sounds = re.findall(r"\(([a-zv]+[1-5])\)", target)
            if (len(sounds) != len(word) or "".join("(" + s + ")" for s in sounds) != target
                    or any(to_normal(s) not in SYLLABLES for s in sounds)):
                raise ValueError("发音修正规则须为逐字括号数字声调拼音")
            value = sounds
        else:
            check_text(target)
            if len(target) > 500:
                raise ValueError("文本转写目标本地上限 500 字")
            value = target
        if word in rules and rules[word] != value:
            raise ValueError("手工字典与位置标注对同一词设置了不同规则")
        rules[word] = value
    generated, _, intended = table_controls(clip, pronunciation_table)
    for word, target in generated.items():
        if word in rules and rules[word] != target:
            raise ValueError(f"发音表与片段字典规则冲突：{word}")
        rules[word] = target
    if len(rules) > 5000:
        raise ValueError("发音字典最多 5000 个词条")
    check_table_matches(text, rules, intended)
    if complete:
        missing = [r for r in scan(text) if r["start"] not in reviewed]
        if missing:
            raise ValueError(f"多音字缺少已校对标注：{missing[0]['text']}@{missing[0]['start']}")
        # 模拟服务端最长匹配，防止一个词组覆盖另一个位置的读音。
        actual, i = {}, 0
        submitted = list(text)
        protected = {}
        for row in rows:
            if row.get("delivery", "spoken_alias" if "spoken_alias" in row else "dictionary") != "dictionary":
                start = row["start"]
                protected.update(zip(range(start, start + len(row["text"])), row["pinyin"]))
            if row.get("spoken_alias"):
                start = row["start"]
                submitted[start:start + len(row["text"])] = row["spoken_alias"]
        text = "".join(submitted)
        known = {r["start"] + j: sound for r in rows for j, sound in enumerate(r["pinyin"])}
        for row in rows:
            delivery = row.get("delivery", "spoken_alias" if "spoken_alias" in row else "dictionary")
            if delivery not in ("instruction", "spoken_alias"):
                continue
            target = row.get("spoken_alias", row["text"])
            for start in range(len(text)):
                if text.startswith(target, start) and any(
                        start + j in known and known[start + j] != sound for j, sound in enumerate(row["pinyin"])):
                    raise ValueError("同词读音指令会影响另一位置；使用明确词组或拆段")
        while i < len(text):
            matches = [w for w in rules if text.startswith(w, i)]
            if matches:
                word = max(matches, key=len)
                value = rules[word]
                if isinstance(value, str):
                    # ponytail: 长度变化不跨位置注音；需要此组合时先明确口播改写，再重新校对。
                    if len(value) != len(word) and any(j in reviewed for j in range(i, i + len(word))):
                        raise ValueError("不同长度文本转写与位置注音相交；先明确口播改写再校对")
                    choices = [pinyin(c, style=Style.TONE3, heteronym=True, neutral_tone_with_five=True)[0]
                               if HAN.fullmatch(c) else [] for c in value]
                    value = [sounds[0] if len(sounds) == 1 else None for sounds in choices]
                actual.update(zip(range(i, i + len(word)), value))
                i += len(word)
            else:
                i += 1
        if any(actual.get(i) != sound for i, sound in expected.items()):
            raise ValueError("发音字典最长匹配与位置标注冲突；调整词组或拆段")
        if any(i in actual and actual[i] != sound for i, sound in protected.items()):
            raise ValueError("发音字典会覆盖自然读法、读音指令或可听别名的目标读音")
    return rows, rules


def resolve_voices(plan, voices=None):
    mapping = {}
    for source in (plan.get("voices", {}), voices if voices is not None else {}):
        if not isinstance(source, dict) or any(not isinstance(role, str) or not role.strip()
                                               for role in source):
            raise ValueError("voices 须为角色到音色 ID 的对象")
        mapping.update(source)
    for voice in mapping.values():
        resolve_resource({"voice": voice})
    clips = plan.get("clips")
    if not isinstance(clips, list) or not clips:
        raise ValueError("计划需要非空 clips")
    resolved, missing = [], set()
    for clip in clips:
        item = dict(clip)
        if "voice" not in item:
            role = item.get("role", "旁白")
            if not isinstance(role, str) or not role.strip():
                raise ValueError("role 必须为非空字符串")
            if role not in mapping:
                missing.add(role)
            else:
                item["voice"] = mapping[role]
        resolved.append(item)
    if missing:
        raise ValueError("缺少角色音色，请在 voices 填写：" + "、".join(sorted(missing)))
    return {**plan, "voices": mapping, "clips": resolved}


def resolve_resource(clip):
    voice = clip["voice"]
    if isinstance(voice, str) and ("替换" in voice or "你的" in voice):
        raise ValueError("音色 ID 是占位值，请填写自己的音色")
    if isinstance(voice, str) and re.fullmatch(r"zh_[a-zA-Z0-9_]+", voice):
        expected = "seed-tts-2.0"
    elif isinstance(voice, str) and re.fullmatch(r"S_[a-zA-Z0-9]+", voice):
        # S_ 不代表训练代际；本工具只接复刻 2.0，不自动探测其他资源。
        expected = "seed-icl-2.0"
    else:
        raise ValueError("需要中文预置音色 ID（zh_）或已有克隆音色 ID（S_）")
    resource = clip.get("resource_id", expected)
    if not isinstance(resource, str) or resource != expected:
        raise ValueError(f"音色 {voice} 在本工具中需要 resource_id={expected}")
    return resource


def request_fingerprint(body, resource):
    # 字幕开关属于请求体，参与指纹；克隆请求额外绑定端点与资源。
    value = body if resource == "seed-tts-2.0" else {
        "endpoint": ENDPOINT, "resource_id": resource, "body": body}
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def perform_fingerprint(body, take):
    value = {"endpoint": PERFORM_ENDPOINT, "model": PERFORM_MODEL, "body": body, "take": take}
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def validate(plan, complete=False):
    plan = resolve_voices(plan)
    table = plan.get("pronunciation_table")
    validate_pronunciations(table)
    if "enable_subtitle" in plan and type(plan["enable_subtitle"]) is not bool:
        raise ValueError("enable_subtitle 必须为布尔值")
    clips = plan.get("clips")
    if not isinstance(clips, list) or not clips:
        raise ValueError("计划需要非空 clips")
    ids = set()
    for clip in clips:
        ident = clip["id"]
        if not isinstance(ident, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", ident) or ident in ids:
            raise ValueError("片段 id 必须唯一且只包含字母数字下划线短横线")
        ids.add(ident)
        mode = clip.get("mode", "tts")
        if mode not in ("tts", "perform"):
            raise ValueError("mode 只能为 tts 或 perform")
        if mode == "tts" and "perform" in clip:
            raise ValueError("perform 配置只允许用于 mode=perform")
        check_text(clip["text"])
        if len(clip["text"]) > 500:
            raise ValueError("单段本地上限 500 字；请明确分段，不截断")
        resolve_resource(clip)
        for name, low, high in (("speech_rate", -50, 100), ("pause_after_ms", 0, 30000)):
            value = clip.get(name, 0)
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f"{name} 必须为 {low}～{high} 的整数")
        if not isinstance(clip.get("direction", ""), str):
            raise ValueError("direction 必须为字符串")
        reference = clip.get("reference_text", "")
        if not isinstance(reference, str) or len(reference) > 500:
            raise ValueError("reference_text 必须为字符串，本地上限 500 字；请选择必要上文，不截断")
        if reference:
            check_text(reference)
        dialect = clip.get("explicit_dialect", "")
        if not isinstance(dialect, str) or (dialect and dialect not in DIALECTS):
            raise ValueError("explicit_dialect 必须为空或官方支持的方言代码")
        if not isinstance(clip.get("section_id", ""), str):
            raise ValueError("section_id 必须为字符串")
        for name in ("enable_subtitle", "enable_latex_tn"):
            if name in clip and type(clip[name]) is not bool:
                raise ValueError(f"{name} 必须为布尔值")
        language = clip.get("explicit_language")
        if language is not None and language not in ("zh-cn", "en"):
            raise ValueError("explicit_language 只能为 zh-cn（中英混读）或 en（英语）")
        if language == "en" and HAN.search(clip["text"]):
            raise ValueError("包含中文的片段须使用 zh-cn 或省略 explicit_language")
        if mode == "perform":
            perform_body(clip, pronunciation_table=table, complete=complete)
        else:
            readings(clip, complete, table)


def load_pronunciations(path):
    def unique(pairs):
        result = {}
        for name, value in pairs:
            if name in result:
                raise ValueError(f"发音表 JSON 字段重复：{name}")
            result[name] = value
        return result
    table = json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=unique)
    if table is None:
        raise ValueError("发音表文件须为对象，不能为 null")
    validate_pronunciations(table)
    return table


def prepare(text, voice=VOICE, resource_id=None, pronunciation_table=None):
    selection = {"voice": voice}
    if resource_id is not None:
        selection["resource_id"] = resource_id
    resource = resolve_resource(selection)
    check_text(text)
    # ponytail: 500 字保守本地上限；需要更长连续朗读时核实账号与模型限制后调整。
    parts, current = [], ""
    start = 0
    for end in sentence_ends(text):
        sentence, start = text[start:end], end
        if len(sentence) > 500:
            raise ValueError("有超过 500 字的连续句子，请明确分段")
        if len(current) + len(sentence) > 500:
            parts.append(current)
            current = ""
        current += sentence
    if current:
        parts.append(current)
    if "".join(parts) != text:
        raise ValueError("分段未保留完整原文")
    clips = [{"id": f"{i:03}", "role": "旁白", "text": part, "voice": voice,
              "direction": "自然、清楚的普通话朗读" if resource == "seed-tts-2.0" else "",
              "reference_text": "", "speech_rate": 0,
              "pause_after_ms": 0, "readings": scan(part)} for i, part in enumerate(parts, 1)]
    if re.search(r"[A-Za-z]", text):
        language = "zh-cn" if HAN.search(text) else "en"
        for clip in clips:
            clip["explicit_language"] = language
            if resource == "seed-tts-2.0":
                clip["direction"] = ("自然、清楚的普通话讲述，英文词按英语发音，中英衔接连贯，不逐字停顿。"
                                     if language == "zh-cn" else "自然、清楚的英语朗读。")
    if resource_id is not None or resource == "seed-icl-2.0":
        for clip in clips:
            clip["resource_id"] = resource
    table = pronunciation_table
    if table is None and re.search(r"[A-Za-z]", text):
        table = load_pronunciations(PRONUNCIATIONS)
    validate_pronunciations(table)
    plan = {"title": "中英阅读" if re.search(r"[A-Za-z]", text) else "中文阅读", "clips": clips}
    if table is not None:
        plan["pronunciation_table"] = json.loads(json.dumps(table))
    return plan


def preview(plan, out, voices=None):
    plan = resolve_voices(plan, voices)
    validate(plan)
    out.mkdir(parents=True, exist_ok=True)
    title = str(plan.get("title", "中文阅读"))
    md, sections = [f"# {title}\n\n读音为校对标注，不进入口播。待校对项尚未确定。\n"], []
    for clip in plan["clips"]:
        rows, _ = readings(clip, pronunciation_table=plan.get("pronunciation_table"))
        mixed_rules, hints, _ = table_controls(clip, plan.get("pronunciation_table"))
        native = [word for word, hint in plan.get("pronunciation_table", {}).get("words", {}).items()
                  if hint is None and token_starts(clip["text"], word)] if plan.get("pronunciation_table") else []
        # 即使手工删掉标注，预览仍展示遗漏候选。
        covered = {i for r in rows for i in range(r["start"], r["start"] + len(r["text"]))}
        rows += [r for r in scan(clip["text"]) if r["start"] not in covered]
        rows.sort(key=lambda r: r["start"])
        cursor, markup, plain, table, details = 0, [], [], [], []
        for row in rows:
            start, word = row["start"], row["text"]
            sound = " ".join(to_tone(s) for s in row["pinyin"])
            status = "已校对" if row["status"] == "reviewed" else "待校对"
            options = "；".join(c + "：" + "/".join(to_tone(p) for p in pinyin(
                c, style=Style.TONE3, heteronym=True, neutral_tone_with_five=True)[0]) for c in word)
            before = clip["text"][cursor:start]
            markup.append(html.escape(before) + f'<ruby class="{row["status"]}" title="{html.escape(status + "；" + options, quote=True)}">'
                          + html.escape(word) + "<rt>" + html.escape(sound) + "</rt></ruby>")
            plain.append(before + f"{word}〔{sound} · {status}〕")
            context = clip["text"][max(0, start - 8):start + len(word) + 8]
            delivery = row.get("delivery", "spoken_alias" if "spoken_alias" in row else "dictionary")
            channel = {"native": "保留自然读法", "dictionary": "发音字典", "instruction": "读音指令", "spoken_alias": "可听替换"}[delivery]
            if row.get("spoken_alias"):
                channel += "：" + row["spoken_alias"]
            cells = [word, sound, status, channel, context, options, str(row.get("note", ""))]
            table.append("<tr>" + "".join("<td>" + html.escape(c) + "</td>" for c in cells) + "</tr>")
            details.append(f'- @{start} {word}：{sound}；{status}；{channel}；语境：{context}；'
                           f'备选：{options}；{row.get("note", "")}\n')
            cursor = start + len(word)
        markup.append(html.escape(clip["text"][cursor:]))
        plain.append(clip["text"][cursor:])
        label = f'{clip["id"]} · {clip.get("role", "旁白")} · {clip["voice"]}'
        controls = [("合成资源", resolve_resource(clip)),
                    ("语音指令", clip.get("direction", "")),
                    ("引用上文（只引用，不朗读）", clip.get("reference_text", "")),
                    ("语速参数", str(clip.get("speech_rate", 0))),
                    ("方言", DIALECTS.get(clip.get("explicit_dialect", ""), "随音色默认")),
                    ("段落标识", clip.get("section_id", "")),
                    ("补充发音字典", "\n".join(clip.get("pronunciation_dict", {}).get("tone", []))),
                    ("语言", clip.get("explicit_language", "默认中英混读")),
                    ("英语原生读法", "、".join(sorted(native))),
                    ("英语读音提示（指令，须试听）", "\n".join(hints)),
                    ("混读发音字典（服务端文本转写）", "\n".join(w + "/" + value for w, value in mixed_rules.items()))]
        if clip.get("mode") == "perform":
            controls[0] = ("合成模型", PERFORM_MODEL)
            controls.extend([("情绪演绎提示词（效果须试听）", perform_body(
                clip, pronunciation_table=plan.get("pronunciation_table"), complete=False)["text_prompt"]),
                ("take 数量", str(clip["perform"].get("takes", 1))),
                ("选定 take", str(clip["perform"].get("selected_take") or "未指定；暂用 take 1"))])
            if clip.get("reference_text"):
                controls.append(("试听警告", "引用上文有被模型念出的风险；结构检查不能代替试听。"))
        md += ["\n## " + label + "\n", "".join(plain) + "\n"]
        md.extend(name + "：" + value + "\n" for name, value in controls if value)
        md.extend(details)
        sections.append("<section><h2>" + html.escape(label) + "</h2><p class=script>" + "".join(markup)
                        + "</p>" + "".join('<p style="white-space:pre-wrap">' + name + "：" + html.escape(value)
                                             + "</p>" for name, value in controls if value)
                        + "<div class=table><table><thead><tr>"
                        + "".join("<th>" + h + "</th>" for h in ["字词", "读音", "状态", "合成处理", "语境", "备选读音", "理由"])
                        + "</tr></thead><tbody>" + "".join(table) + "</tbody></table></div></section>")
    (out / "director.md").write_text("".join(md), encoding="utf-8")
    page = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>中英阅读稿</title><style>body{max-width:1040px;margin:40px auto;padding:0 24px;color:#203038;background:#f7f5ef;font-family:system-ui,sans-serif}section{background:white;border:1px solid #deded5;border-radius:12px;padding:24px;margin:24px 0}h2{font-size:15px;color:#526369}.script{font-size:23px;line-height:2.5;white-space:pre-wrap}ruby.reviewed{background:#e3f1e9}ruby.pending{background:#ffe8b4}rt{font-size:12px;color:#435d59}table{border-collapse:collapse;width:100%;font-size:13px}td,th{text-align:left;padding:10px;border-bottom:1px solid #eee}.table{overflow:auto}button{padding:8px 16px;cursor:pointer}.hide rt{visibility:hidden}@media(max-width:600px){body{padding:0 12px}section{padding:16px}}</style>
<h1>''' + html.escape(title) + '''</h1><p>中英阅读稿 · 黄色待校对，绿色已校对。注音与导演说明不进入口播。本页不证明已生成音频。</p>
<button onclick="document.body.classList.toggle('hide')">显示／隐藏注音</button>''' + "".join(sections) + "</html>"
    (out / "director.html").write_text(page, encoding="utf-8")


def request_body(clip, enable_subtitle=None, pronunciation_table=None):
    if enable_subtitle is None:
        enable_subtitle = clip.get("enable_subtitle", True)
    if type(enable_subtitle) is not bool:
        raise ValueError("enable_subtitle 必须为布尔值")
    # 官方不支持方言及 LaTeX 文本规范化请求的字幕，保留音频合成并降级。
    enable_subtitle = enable_subtitle and not clip.get("explicit_dialect") and not clip.get("enable_latex_tn", False)
    rows, rules = readings(clip, complete=True, pronunciation_table=pronunciation_table)
    _, hints, _ = table_controls(clip, pronunciation_table)
    text, instructions = list(clip["text"]), []
    additions = {"disable_markdown_filter": True}
    if clip.get("explicit_language"):
        additions["explicit_language"] = clip["explicit_language"]
    if rules:
        additions["pronunciation_dict"] = {"tone": [w + "/" + (sounds if isinstance(sounds, str)
                                                   else "".join("(" + s + ")" for s in sounds))
                                                   for w, sounds in rules.items()]}
    if clip.get("direction"):
        instructions.append(clip["direction"])
    if clip.get("reference_text"):
        instructions.append("以下为引用上文，只用于理解并承接语境与情绪，不朗读：\n"
                            + clip["reference_text"])
    if clip.get("explicit_dialect"):
        additions["explicit_dialect"] = clip["explicit_dialect"]
    if clip.get("section_id"):
        additions["section_id"] = clip["section_id"]
    if "enable_latex_tn" in clip:
        additions["enable_latex_tn"] = clip["enable_latex_tn"]
    for row in rows:
        delivery = row.get("delivery", "spoken_alias" if "spoken_alias" in row else "dictionary")
        if delivery == "spoken_alias":
            start = row["start"]
            text[start:start + len(row["text"])] = row["spoken_alias"]
        if delivery in ("instruction", "spoken_alias"):
            target = row.get("spoken_alias", row["text"])
            instructions.append(f'发音要求：原文“{row["text"]}”，本次提交的“{target}”读作 {" ".join(row["pinyin"])}。')
    if hints:
        instructions.append("以下仅为发音提示，不朗读提示本身：\n" + "\n".join(hints))
    if instructions:
        # 全部说明合入首条，避免后续指令被忽略。
        additions["context_texts"] = ["\n".join(instructions)]
    return {"req_params": {"text": "".join(text), "speaker": clip["voice"],
            "audio_params": {"format": "pcm", "sample_rate": 24000,
                             "speech_rate": clip.get("speech_rate", 0),
                             "enable_subtitle": enable_subtitle},
            "additions": json.dumps(additions, ensure_ascii=False)}}


def perform_body(clip, enable_subtitle=None, pronunciation_table=None, complete=True):
    config = clip.get("perform")
    if not isinstance(config, dict):
        raise ValueError("mode=perform 需要 perform 对象")
    unknown = set(config) - {"prompt", "takes", "selected_take", "ambience"}
    if unknown:
        raise ValueError("未知 perform 字段：" + "、".join(sorted(unknown)))
    prompt = config.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 500:
        raise ValueError("perform.prompt 须为 1～500 字的导演说明，台词只放 text")
    takes, selected = config.get("takes", 1), config.get("selected_take")
    if type(takes) is not int or not 1 <= takes <= 4:
        raise ValueError("perform.takes 须为 1～4 的整数")
    if selected is not None and (type(selected) is not int or not 1 <= selected <= takes):
        raise ValueError("perform.selected_take 须为 null 或 1～takes 的整数")
    if type(config.get("ambience", False)) is not bool:
        raise ValueError("perform.ambience 须为布尔值")
    if len(clip["text"]) > 400:
        raise ValueError("perform 台词本地上限 400 字，请拆段")
    if "explicit_language" in clip and clip["explicit_language"] not in ("zh-cn", "en"):
        raise ValueError("perform 的 explicit_language 只能为 zh-cn 或 en")
    for name in ("explicit_dialect", "enable_latex_tn", "section_id", "pronunciation_dict"):
        if name in clip:
            raise ValueError(f"perform 不支持 {name}；发音请用 spoken_alias / instruction，或保留 TTS")
    for row in clip.get("readings", []):
        if row.get("delivery", "spoken_alias" if "spoken_alias" in row else "dictionary") == "dictionary":
            raise ValueError("perform 不支持 dictionary；请改用 spoken_alias / instruction，或保留 TTS")
    rows, rules = readings(clip, complete=complete, pronunciation_table=pronunciation_table)
    if rules:
        raise ValueError("perform 不支持发音表缩写/型号转写；请改用 spoken_alias / instruction，或保留 TTS")
    _, hints, _ = table_controls(clip, pronunciation_table)
    text, instructions = list(clip["text"]), []
    for row in rows:
        delivery = row.get("delivery", "spoken_alias" if "spoken_alias" in row else "dictionary")
        if delivery == "spoken_alias":
            start = row["start"]
            text[start:start + len(row["text"])] = row["spoken_alias"]
        if delivery in ("instruction", "spoken_alias"):
            target = row.get("spoken_alias", row["text"])
            instructions.append(f'原文“{row["text"]}”，本次提交的“{target}”读作 {" ".join(row["pinyin"])}。')
    role = clip.get("role", "旁白")
    if not isinstance(role, str) or not role.strip():
        raise ValueError("role 必须为非空字符串")
    text = "".join(text)
    # 音色只由 references[].speaker 指定，不在描述中添加音频引用标记。
    lines = [f'“{role}”全程只用指定音色。']
    if clip.get("direction"):
        lines.append(f'{role}的整体语气：{clip["direction"]}')
    if clip.get("reference_text"):
        lines.append("上文（只用于理解情绪，不要念出来）：" + clip["reference_text"])
    lines.append(f'{role}{prompt}：“{text}”')
    if instructions or hints:
        lines.append("发音要求：" + "\n".join(instructions + hints))
    if not config.get("ambience", False):
        lines.append("只生成这一个角色的人声干声，不要背景音乐、环境声或音效，不要添加台词以外的话。")
    text_prompt = "\n".join(lines)
    if len(text_prompt) > 3000:
        raise ValueError("perform 拼接后的 text_prompt 超过 3000 字符，请缩短导演说明或拆段")
    if enable_subtitle is None:
        enable_subtitle = clip.get("enable_subtitle", True)
    if type(enable_subtitle) is not bool:
        raise ValueError("enable_subtitle 必须为布尔值")
    return {"model": PERFORM_MODEL, "text_prompt": text_prompt,
            "references": [{"speaker": clip["voice"]}],
            "audio_config": {"format": "wav", "sample_rate": 24000,
                             "speech_rate": clip.get("speech_rate", 0), "enable_subtitle": enable_subtitle}}


def subtitle_body(clip, body):
    # 仅供本地字幕处理复用，不发送到服务端，也不参与请求指纹。
    if "req_params" in body:
        return body
    text = list(clip["text"])
    for row in clip.get("readings", []):
        if row.get("spoken_alias"):
            start = row["start"]
            text[start:start + len(row["text"])] = row["spoken_alias"]
    return {"req_params": {"text": "".join(text), "audio_params": body["audio_config"]}}


def debug_frame(frame, secret):
    sensitive = r"key|token|authorization|secret|cookie|password|url"
    hidden = {secret} if secret else set()
    def collect(value):
        if isinstance(value, dict):
            for name, item in value.items():
                if (name in ("audio", "data") or re.search(sensitive, name, re.I)) and isinstance(item, str) and item:
                    hidden.add(item)
                collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)
    collect(frame)
    hidden = sorted(hidden, key=len, reverse=True)
    def redact(value):
        if isinstance(value, dict):
            return {redact(name): ("[REDACTED]" if re.search(sensitive, name, re.I) else
                f"[base64: {len(item)} characters]" if name in ("audio", "data") and isinstance(item, str)
                else redact(item)) for name, item in value.items()}
        if isinstance(value, list):
            return [redact(item) for item in value]
        if isinstance(value, str):
            for item in hidden:
                value = value.replace(item, "[REDACTED]")
        return value
    print("stream_frame: " + json.dumps(redact(frame), ensure_ascii=False), file=sys.stderr)


def decode_stream(lines, debug=None):
    audio, usage, subtitles, finished = bytearray(), None, [], False
    for line in lines:
        if not line.strip():
            continue
        frame = json.loads(line)
        if debug is not None:
            debug(frame)
        code = frame.get("code")
        if code not in (0, 20000000):
            raise RuntimeError(f"火山返回错误码 {code}")
        if frame.get("data"):
            audio.extend(base64.b64decode(frame["data"], validate=True))
        if frame.get("usage") is not None:
            usage = frame["usage"]
        # HTTP JSON 行使用 sentence 对象，不是 WebSocket 的字幕事件封装。
        if isinstance(frame.get("sentence"), dict):
            subtitles.append(frame["sentence"])
        if code == 20000000:
            finished = True
        # 读到响应 EOF；不在最后一个音频包或完成码处丢弃晚到的字幕。
    if not finished or not audio or len(audio) % 2:
        raise RuntimeError("音频流未完整结束或 PCM 数据无效")
    return bytes(audio), usage, subtitles


def record_perform_error(entry, payload, key):
    if not isinstance(payload, dict):
        return
    if type(payload.get("code")) is int:
        entry["error_code"] = payload["code"]
    message = payload.get("message")
    if isinstance(message, str):
        for secret in (key, payload.get("audio"), payload.get("url")):
            if isinstance(secret, str) and secret:
                message = message.replace(secret, "[REDACTED]")
        entry["error_message"] = message[:2000]


def decode_perform(payload):
    # 2026-10-12 真实响应与官方示例均可省略 code；出现时仍严格校验。
    code = payload.get("code", 0) if isinstance(payload, dict) else None
    if type(code) is not int or code not in (0, 20000000):
        raise ValueError("音频生成返回失败或无效状态码")
    audio = payload.get("audio")
    if not isinstance(audio, str) or not audio:
        raise ValueError("音频生成响应缺少 audio")
    raw = base64.b64decode(audio, validate=True)
    with wave.open(io.BytesIO(raw), "rb") as wav:
        channels = wav.getnchannels()
        if wav.getframerate() != 24000 or wav.getsampwidth() != 2 or channels not in (1, 2):
            raise ValueError("perform 必须返回 24000 Hz、16 bit、单声道或双声道 WAV")
        frames = wav.getnframes()
        pcm = wav.readframes(frames)
        if frames <= 0 or len(pcm) != frames * channels * 2:
            raise ValueError("perform WAV 为空或不完整")
    if channels == 2:
        mono = bytearray(frames * 2)
        for i, (left, right) in enumerate(struct.iter_unpack("<hh", pcm)):
            struct.pack_into("<h", mono, i * 2, int((left + right) / 2))
        pcm = bytes(mono)
    return pcm, channels == 2


def perform_subtitles(clip, body, payload, duration):
    adapted = subtitle_body(clip, body)
    if not body["audio_config"]["enable_subtitle"]:
        data, reason = clip_subtitles(clip, adapted, [], duration)
        return data, reason, None
    subtitle = payload.get("subtitle")
    if subtitle is None:
        data, reason = clip_subtitles(clip, adapted, [], duration)
        return data, reason, None
    text_match = None
    try:
        if not isinstance(subtitle, dict):
            raise ValueError("字幕对象无效")
        if isinstance(subtitle.get("text"), str):
            text_match = lexical_text(subtitle["text"]) == lexical_text(adapted["req_params"]["text"])
        sentences = subtitle.get("sentences")
        if not isinstance(sentences, list):
            raise ValueError("字幕 sentences 无效")
        if any(not isinstance(sentence, dict) or not isinstance(sentence.get("text"), str)
               for sentence in sentences):
            raise ValueError("字幕句子无效")
        if sentences:
            sentence_match = lexical_text("".join(s["text"] for s in sentences)) == lexical_text(adapted["req_params"]["text"])
            text_match = sentence_match if text_match is None else text_match and sentence_match
        events = []
        for sentence in sentences:
            start, end = sentence.get("start_time"), sentence.get("end_time")
            if (type(start) is not int or type(end) is not int
                    or not valid_subtitle_span(start / 1000, end / 1000, duration)):
                raise ValueError("字幕句子毫秒时间无效")
            raw_words = sentence.get("words")
            if not isinstance(raw_words, list):
                raise ValueError("字幕 words 无效")
            words = []
            for word in raw_words:
                if not isinstance(word, dict):
                    raise ValueError("字幕字词无效")
                left, right = word.get("start_time"), word.get("end_time")
                if (type(left) is not int or type(right) is not int or not start <= left <= right <= end):
                    raise ValueError("字幕字词毫秒时间无效")
                words.append({"word": word.get("text"), "startTime": left / 1000, "endTime": right / 1000})
            events.append({"text": sentence["text"], "words": words})
        data, reason = clip_subtitles(clip, adapted, events, duration)
        if data["words"] and lexical_text(data["text"]) != lexical_text(adapted["req_params"]["text"]):
            text_match = False
    except (ValueError, OverflowError):
        data = {"text": adapted["req_params"]["text"], "words": [], "sentences": []}
        reason = "invalid_subtitles"
    return data, reason, text_match


def finite_number(value):
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def valid_subtitle_span(start, end, duration=None):
    if not finite_number(start) or not finite_number(end):
        return False
    # 服务端时间有毫秒量化，容许 10ms 舍入误差，但不裁剪或猜测时间。
    return 0 <= start <= end and (duration is None or end <= duration + 0.01)


def normalize_words(raw_words, duration=None):
    if not isinstance(raw_words, list):
        raise ValueError("字幕字词列表无效")
    unique = {}
    for raw in raw_words:
        if not isinstance(raw, dict) or not isinstance(raw.get("word"), str) or not raw["word"].strip():
            raise ValueError("字幕字词无效")
        start, end = raw.get("startTime"), raw.get("endTime")
        if not valid_subtitle_span(start, end, duration):
            raise ValueError("字幕时间无效或超过音频时长")
        if "confidence" in raw and (not finite_number(raw["confidence"]) or not 0 <= raw["confidence"] <= 1):
            raise ValueError("字幕置信度无效")
        unique[(raw["word"], start, end)] = {
            name: raw[name] for name in ("word", "startTime", "endTime", "confidence") if name in raw}
    words = sorted(unique.values(), key=lambda w: (w["startTime"], w["endTime"]))
    if any(a["endTime"] > b["endTime"] for a, b in zip(words, words[1:])):
        raise ValueError("字幕结束时间不单调")
    return words


def lexical_text(text):
    return "".join(char for char in text if char.isalnum())


def align_word_spans(text, words):
    positions = [i for i, char in enumerate(text) if char.isalnum()]
    lexical = lexical_text(text)
    spans, cursor = [], 0
    for word in words:
        token = word["word"]
        start = text.find(token, cursor)
        if start >= 0:
            end = start + len(token)
        elif lexical_text(token):
            offset = next((i for i, pos in enumerate(positions) if pos >= cursor), len(positions))
            match = lexical.find(lexical_text(token), offset)
            if match < 0:
                spans.append(None)
                continue
            start, end = positions[match], positions[match + len(lexical_text(token)) - 1] + 1
        else:
            # 句末标点修订可沿用同一字词时间，但不能把文字内容也当作标点忽略。
            start = next((i for i in range(cursor, len(text))
                          if not text[i].isalnum() and not text[i].isspace()), -1)
            if start < 0:
                spans.append(None)
                continue
            end = start + 1
        spans.append((start, end))
        cursor = end
    return spans


def sentence_cues(text, words):
    if not words:
        return []
    spans = align_word_spans(text, words)
    boundaries = [0] + sentence_ends(text)
    # 未对齐的规范化字词只用相邻真实文字锚点定位；跨界或无锚点则合并字幕。
    for i, span in enumerate(spans):
        if span is None:
            left = next((spans[j][1] for j in range(i - 1, -1, -1) if spans[j] is not None), 0)
            right = next((spans[j][0] for j in range(i + 1, len(spans)) if spans[j] is not None), len(text))
            if left >= right:
                return [{"text": text, "startTime": words[0]["startTime"], "endTime": words[-1]["endTime"]}]
            span = (left, right)
        boundaries = [cut for cut in boundaries if not span[0] < cut < span[1]]
    groups, prefix = [], ""
    for start, end in zip(boundaries, boundaries[1:]):
        owned = []
        for i, span in enumerate(spans):
            if span is None:
                left = next((spans[j][1] for j in range(i - 1, -1, -1) if spans[j] is not None), 0)
                right = next((spans[j][0] for j in range(i + 1, len(spans)) if spans[j] is not None), len(text))
                span = (left, right)
            if span[0] < end and span[1] > start:
                owned.append(i)
        caption = text[start:end].strip()
        if owned:
            groups.append({"text": prefix + caption, "indices": owned})
            prefix = ""
        elif groups:
            groups[-1]["text"] += caption
        else:
            prefix += caption
    for i in range(len(groups) - 1, -1, -1):
        group = groups[i]
        first, last = words[group["indices"][0]], words[group["indices"][-1]]
        if first["startTime"] == last["endTime"] and not lexical_text(group["text"]):
            if i and words[groups[i - 1]["indices"][-1]]["endTime"] == first["startTime"]:
                groups[i - 1]["text"] += group["text"]
                groups[i - 1]["indices"].extend(group["indices"])
                groups.pop(i)
            elif i + 1 < len(groups) and words[groups[i + 1]["indices"][0]]["startTime"] == last["endTime"]:
                groups[i + 1]["text"] = group["text"] + groups[i + 1]["text"]
                groups[i + 1]["indices"] = group["indices"] + groups[i + 1]["indices"]
                groups.pop(i)
    return [{"text": group["text"], "startTime": words[group["indices"][0]]["startTime"],
             "endTime": words[group["indices"][-1]]["endTime"]} for group in groups]


def validate_cues(data, duration=None):
    cues, words = data["sentences"], data["words"]
    if not isinstance(cues, list) or not isinstance(data["text"], str):
        raise ValueError("字幕句子列表或文字无效")
    previous = 0
    for cue in cues:
        if not isinstance(cue, dict) or not isinstance(cue.get("text"), str) or not cue["text"].strip():
            raise ValueError("字幕句子文字无效")
        start, end = cue.get("startTime"), cue.get("endTime")
        if not valid_subtitle_span(start, end, duration) or start >= end or start < previous:
            raise ValueError("字幕句子时间无效")
        previous = end
    compact = lambda value: re.sub(r"\s+", "", value)
    if compact(data["text"]) != "".join(compact(cue["text"]) for cue in cues) and words:
        raise ValueError("字幕句子未覆盖文字")
    if not words:
        if cues:
            raise ValueError("空字词字幕不能包含句子")
        return
    # 字词成员由文字区间和有序索引确定；共享时间边界不等于共享字词。
    positions = [i for i, char in enumerate(data["text"]) if not char.isspace()]
    owners, cursor = {}, 0
    spans = align_word_spans(data["text"], words)
    for index, cue in enumerate(cues):
        length = len(compact(cue["text"]))
        left, right = positions[cursor], positions[cursor + length - 1] + 1
        for i, span in enumerate(spans):
            if span is not None and span[0] < right and span[1] > left:
                if i in owners:
                    raise ValueError("字幕句界切开了同一字词")
                owners[i] = index
        cursor += length
    # 规范化文字不能逐字匹配时，只接受唯一的连续真实首尾时间分区。
    partitions = {0: [()]}
    for index, cue in enumerate(cues):
        next_partitions = {}
        expected = [i for i, owner in owners.items() if owner == index]
        for first, paths in partitions.items():
            if first == len(words) or words[first]["startTime"] != cue["startTime"]:
                continue
            for last in range(first, len(words)):
                word = words[last]
                if word["startTime"] < cue["startTime"] or word["endTime"] > cue["endTime"]:
                    break
                if word["endTime"] != cue["endTime"]:
                    continue
                if expected and not first <= min(expected) <= max(expected) <= last:
                    continue
                if any(owners.get(i, index) != index for i in range(first, last + 1)):
                    continue
                candidates = next_partitions.setdefault(last + 1, [])
                candidates.extend(path + ((first, last + 1),) for path in paths)
                del candidates[2:]
        partitions = next_partitions
    if len(partitions.get(len(words), [])) != 1:
        raise ValueError("字幕句子与字词文字或时间归属不一致")


def normalize_cached_subtitles(cached, duration):
    if not isinstance(cached, dict) or not isinstance(cached.get("text"), str) or "words" not in cached:
        raise ValueError("字幕缓存缺少 text 或 words")
    words = normalize_words(cached["words"], duration)
    data = {"text": cached["text"], "words": words,
            "sentences": cached["sentences"] if "sentences" in cached else sentence_cues(cached["text"], words)}
    validate_cues(data, duration)
    data["sentences"] = [{name: cue[name] for name in ("text", "startTime", "endTime")}
                         for cue in data["sentences"]]
    return data


def subtitle_data(events, text, duration=None):
    groups = []
    for event in events:
        if not isinstance(event, dict) or not isinstance(event.get("text", ""), str):
            raise ValueError("字幕格式无效")
        local = normalize_words(event.get("words", []), duration)
        if not local:
            continue
        start, end = local[0]["startTime"], local[-1]["endTime"]
        overlapping = [group for group in groups if
                       (group["words"][0]["startTime"] < end and start < group["words"][-1]["endTime"])
                       or (start == end == group["words"][0]["startTime"] == group["words"][-1]["endTime"])]
        overlapping.sort(key=lambda group: group["words"][0]["startTime"])
        if overlapping:
            old = [word for group in overlapping for word in group["words"]]
            old_text = lexical_text("".join(word["word"] for word in old))
            new_text = lexical_text("".join(word["word"] for word in local))
            identity = lambda word: (word["word"], word["startTime"], word["endTime"])
            old_ids, new_ids = [identity(word) for word in old], [identity(word) for word in local]
            if len(local) < len(old) and old_ids[:len(local)] == new_ids:
                continue
            anchored = old_ids[0] == new_ids[0] and len(local) >= len(old) and (
                start <= old[0]["startTime"] + 0.01 and end >= old[-1]["endTime"] - 0.01)
            if not (old_text and new_text.startswith(old_text)) and not anchored and old_ids != new_ids:
                raise ValueError("字幕部分重叠，无法可靠合并")
            # 先替换整组再展开，避免最新快照修订字词或时间后遗留旧三元组。
            groups = [group for group in groups if group not in overlapping]
        groups.append({"text": event.get("text") or "".join(word["word"] for word in local), "words": local})
    groups.sort(key=lambda group: group["words"][0]["startTime"])
    words = normalize_words([word for group in groups for word in group["words"]], duration)
    cues = [cue for group in groups for cue in sentence_cues(group["text"], group["words"])]
    data = {"text": "".join(group["text"] for group in groups) or text, "words": words, "sentences": cues}
    validate_cues(data, duration)
    return data


def clip_subtitles(clip, body, events, duration=None):
    reason = ""
    if clip.get("explicit_dialect"):
        reason = "explicit_dialect"
    elif clip.get("enable_latex_tn", False):
        reason = "enable_latex_tn"
    elif not body["req_params"]["audio_params"]["enable_subtitle"]:
        reason = "disabled"
    if not reason:
        try:
            data = subtitle_data(events, body["req_params"]["text"], duration)
        except ValueError:
            reason = "invalid_subtitles"
        else:
            if data["words"]:
                return data, ""
            reason = "not_returned"
    return {"text": body["req_params"]["text"], "words": [], "sentences": []}, reason


def build_timeline(segments):
    frames, clips, words, sentences = 0, [], [], []
    for segment in segments:
        clip, data = segment["clip"], segment["subtitles"]
        offset = frames / 24000
        duration = segment["frames"] / 24000
        pause = clip.get("pause_after_ms", 0)
        clips.append({"id": clip["id"], "text": clip["text"], "subtitle_text": data["text"],
                      "offset": offset, "duration": duration, "pause_after_ms": pause,
                      "audio": segment["audio"], "words_file": segment["words_file"],
                      "timestamps": bool(data["words"]), "timestamps_reason": segment["timestamps_reason"],
                      "mode": clip.get("mode", "tts"), "take": segment.get("take", 1),
                      "take_selection": segment.get("take_selection", "single"),
                      "text_match": segment.get("text_match"), "rms_dbfs": segment.get("rms_dbfs")})
        for name, target in (("words", words), ("sentences", sentences)):
            for item in data[name]:
                target.append({**item, "clip": clip["id"],
                               "startTime": round(offset + item["startTime"], 9),
                               "endTime": round(offset + item["endTime"], 9)})
        frames += segment["frames"] + 24 * pause
    return {"sample_rate": 24000, "duration": frames / 24000,
            "timestamps": all(clip["timestamps"] for clip in clips),
            "clips": clips, "words": words, "sentences": sentences}


def srt_text(timeline):
    def stamp(seconds):
        milliseconds = round(seconds * 1000)
        seconds, ms = divmod(milliseconds, 1000)
        minutes, sec = divmod(seconds, 60)
        hours, minute = divmod(minutes, 60)
        return f"{hours:02}:{minute:02}:{sec:02},{ms:03}"
    return "".join(f"{i}\n{stamp(cue['startTime'])} --> {stamp(cue['endTime'])}\n"
                   + " ".join(cue["text"].split()) + "\n\n"
                   for i, cue in enumerate(timeline["sentences"], 1))


def wav_bytes(pcm):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(pcm)
    return buffer.getvalue()


def wav_frames(wav):
    if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, 24000):
        raise ValueError("缓存音频格式错误")
    frames = wav.getnframes()
    if frames <= 0:
        raise ValueError("缓存音频为空")
    return frames


def pcm_chunks(wav, frames):
    remaining = frames
    while remaining:
        count = min(remaining, PCM_CHUNK_FRAMES)
        chunk = wav.readframes(count)
        if len(chunk) != count * 2:
            raise ValueError("缓存音频不完整")
        yield chunk
        remaining -= count


def inspect_cached_wav(path):
    with wave.open(str(path), "rb") as wav:
        frames = wav_frames(wav)
        for _ in pcm_chunks(wav, frames):
            pass
    return frames


def rms_dbfs(path):
    total = 0
    with wave.open(str(path), "rb") as wav:
        frames = wav_frames(wav)
        for chunk in pcm_chunks(wav, frames):
            total += sum(sample * sample for (sample,) in struct.iter_unpack("<h", chunk))
    # 数字静音没有有限 dBFS 值；JSON 用 null，不写非标准的 -Infinity。
    return round(10 * math.log10(total / frames / (32768 ** 2)), 3) if total else None


def write_pcm_wav(path, pcm):
    temp = path.with_suffix(".tmp")
    with wave.open(str(temp), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        view = memoryview(pcm)
        for start in range(0, len(pcm), PCM_CHUNK_FRAMES * 2):
            wav.writeframesraw(view[start:start + PCM_CHUNK_FRAMES * 2])
    temp.replace(path)


def concatenate_wavs(segments, final_path):
    temp = final_path.with_suffix(".tmp")
    silence = b"\0\0" * PCM_CHUNK_FRAMES
    try:
        with wave.open(str(temp), "wb") as final:
            final.setnchannels(1)
            final.setsampwidth(2)
            final.setframerate(24000)
            for segment in segments:
                with wave.open(str(final_path.parent / segment["audio"]), "rb") as wav:
                    if wav_frames(wav) != segment["frames"]:
                        raise ValueError("拼接时缓存音频帧数发生变化")
                    for chunk in pcm_chunks(wav, segment["frames"]):
                        final.writeframesraw(chunk)
                remaining = 24 * segment["clip"].get("pause_after_ms", 0)
                while remaining:
                    count = min(remaining, PCM_CHUNK_FRAMES)
                    final.writeframesraw(silence[:count * 2])
                    remaining -= count
        temp.replace(final_path)
    except Exception:
        if temp.exists():
            temp.unlink()
        raise


def read_cached_clip(clip, body, out, fingerprint, entry, sidecar_updates=None):
    try:
        frames = inspect_cached_wav(out / (fingerprint + ".wav"))
        words_path = out / (fingerprint + ".words.json")
        cached = json.loads(words_path.read_text(encoding="utf-8")) if words_path.exists() else None
        if body["req_params"]["audio_params"]["enable_subtitle"]:
            data = normalize_cached_subtitles(cached, frames / 24000)
            reason = "" if data["words"] else entry.get("timestamps_reason") or "not_returned"
        else:
            data, reason = clip_subtitles(clip, body, [])
        if "timestamps" in entry and (type(entry["timestamps"]) is not bool or entry["timestamps"] != bool(data["words"])):
            raise ValueError("字幕缓存与已记录的 timestamps 状态不一致")
        if sidecar_updates is not None and cached != data:
            sidecar_updates[words_path] = data
        return frames, data, reason
    except (ValueError, KeyError, TypeError, OSError, wave.Error, EOFError):
        raise RuntimeError(f"片段 {clip['id']} 的音频或字幕缓存无效；需要重新渲染。"
                           "请核对费用与授权后使用新的输出目录；未自动重发") from None


def render(plan, out, dry_run=False, retry_uncertain=False, timestamps=None, debug_stream=False,
           voices=None, only_mode=None):
    plan = resolve_voices(plan, voices)
    validate(plan, complete=True)
    if timestamps is not None and type(timestamps) is not bool:
        raise ValueError("timestamps 必须为布尔值")
    if only_mode not in (None, "tts", "perform"):
        raise ValueError("only_mode 只能为 tts 或 perform")
    jobs, attempts = [], []
    for clip in plan["clips"]:
        mode = clip.get("mode", "tts")
        enabled = timestamps if timestamps is not None else clip.get("enable_subtitle", plan.get("enable_subtitle", True))
        builder = perform_body if mode == "perform" else request_body
        body = builder(clip, enabled, plan.get("pronunciation_table"))
        route = {"mode": mode, "endpoint": PERFORM_ENDPOINT if mode == "perform" else ENDPOINT,
                 "takes": clip["perform"].get("takes", 1) if mode == "perform" else 1}
        route.update({"model": PERFORM_MODEL} if mode == "perform" else {"resource_id": resolve_resource(clip)})
        jobs.append((clip, body, route))
        for take in range(1, route["takes"] + 1):
            fingerprint = (perform_fingerprint(body, take) if mode == "perform" else
                           request_fingerprint(body, route["resource_id"]))
            attempts.append((clip, body, route, take, fingerprint))
    routes = [{"clip": clip["id"], "speaker": clip["voice"], **route} for clip, _, route in jobs]
    out.mkdir(parents=True, exist_ok=True)
    save(out / "requests.json", [body for _, body, _ in jobs])
    save(out / "routes.json", routes)
    if dry_run:
        counts = {"tts": {"clips": 0, "characters": 0},
                  "perform": {"clips": 0, "takes": 0, "calls": 0, "characters": 0, "estimated_seconds": 0}}
        for clip, body, route in jobs:
            if only_mode is not None and route["mode"] != only_mode:
                continue
            count = counts[route["mode"]]
            characters = len(subtitle_body(clip, body)["req_params"]["text"])
            count["clips"] += 1
            count["characters"] += characters
            if route["mode"] == "perform":
                count["takes"] += route["takes"]
                count["calls"] += route["takes"]
                count["estimated_seconds"] += (characters * 0.3 + 2) * route["takes"]
        counts["perform"]["estimated_seconds"] = round(counts["perform"]["estimated_seconds"], 3)
        return {"dry_run": True, "clips": len(jobs),
                "characters": sum(len(c["text"]) for c, _, _ in jobs), "routes": routes, **counts,
                "perform_cost_note": "按生成时长计费，约 1 元/分钟，以控制台为准",
                "estimate_note": "秒数仅为提交文本字数 × 0.3 + 2 的每 take 粗估；calls 为不考虑缓存的调用上限"}
    key = os.environ.get("VOLC_TTS_API_KEY")
    if not key:
        raise ValueError("运行环境缺少 VOLC_TTS_API_KEY")
    manifest_path = out / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    cached_clips, sidecar_updates, manifest_dirty = {}, {}, False
    for clip, body, route, take, fingerprint in attempts:
        entry = manifest.get(fingerprint, {})
        old, legacy = {}, fingerprint
        eligible = only_mode is None or route["mode"] == only_mode
        if route["mode"] == "tts":
            resource = route["resource_id"]
            legacy_body = json.loads(json.dumps(body))
            del legacy_body["req_params"]["audio_params"]["enable_subtitle"]
            legacy = request_fingerprint(legacy_body, resource)
            if resource != "seed-tts-2.0" and any(request_fingerprint(b, "seed-tts-2.0") in manifest
                                                for b in (body, legacy_body)):
                raise RuntimeError("已有未绑定资源的旧克隆请求记录；请先核对服务记录，不自动复用或重发")
            old = manifest.get(legacy, {}) if entry.get("status") != "complete" else {}
        if eligible and not retry_uncertain and any(e.get("status") == "uncertain" for e in (entry, old)):
            raise RuntimeError("已有结果不确定的请求；核对服务记录与授权后才能 --retry-uncertain")
        adapted = subtitle_body(clip, body)
        if adapted["req_params"]["audio_params"]["enable_subtitle"]:
            for cached, record in ((fingerprint, entry), (legacy, old)):
                if record.get("status") == "complete" and not (out / (cached + ".words.json")).is_file():
                    raise RuntimeError(f"片段 {clip['id']} 已有音频缓存但缺少 words.json；需要重新渲染以获取时间戳。"
                                       "请核对费用与授权后使用新的输出目录；未自动重发")
        if entry.get("status") == "complete" and fingerprint not in cached_clips:
            # 包含所有 perform take 和跳过模式的缓存；任何新调用前统一校验。
            cached_clips[fingerprint] = read_cached_clip(clip, adapted, out, fingerprint, entry, sidecar_updates)
            frames, data, reason = cached_clips[fingerprint]
            metadata = {"words_file": fingerprint + ".words.json", "timestamps": bool(data["words"]),
                        "timestamps_reason": reason}
            if any(entry.get(name) != value for name, value in metadata.items()):
                entry.update(metadata)
                manifest_dirty = True
    for path, data in sidecar_updates.items():
        save(path, data)
    segments, takes_index, missing, pending, mismatches = [], {}, [], [], []
    for clip, body, route, take, fingerprint in attempts:
        mode = route["mode"]
        audio_path = out / (fingerprint + ".wav")
        words_path = out / (fingerprint + ".words.json")
        entry = manifest.get(fingerprint, {})
        if entry.get("status") == "complete":
            frames, data, reason = cached_clips[fingerprint]
        elif only_mode is not None and mode != only_mode:
            selected = clip.get("perform", {}).get("selected_take") or 1
            if take == selected:
                missing.append(clip["id"])
            continue
        else:
            request_id = str(uuid.uuid4())
            entry = {"status": "uncertain", "request_id": request_id, "clip": clip["id"],
                     **route, "take": take}
            manifest[fingerprint] = entry
            save(manifest_path, manifest)
            manifest_dirty = False
            headers = {"Content-Type": "application/json", "X-Api-Key": key, "X-Api-Request-Id": request_id}
            if mode == "tts":
                headers["X-Api-Resource-Id"] = route["resource_id"]
            request = urllib.request.Request(route["endpoint"], data=json.dumps(body, ensure_ascii=False).encode(),
                                             headers=headers, method="POST")
            started = time.monotonic()
            try:
                # 不跟随重定向，避免凭据转发到另一目的地。
                opener = urllib.request.build_opener(NoRedirect)
                with opener.open(request, timeout=300 if mode == "perform" else 90) as response:
                    logid = response.headers.get("X-Tt-Logid")
                    entry["logid"] = logid.replace(key, "[REDACTED]") if isinstance(logid, str) else None
                    if mode == "perform":
                        entry["http_status"] = getattr(response, "status", 200)
                        payload = json.load(response)
                        if debug_stream:
                            debug_frame(payload, key)
                        if isinstance(payload, dict):
                            entry["response_code_present"] = "code" in payload
                            entry["response_code"] = payload.get("code") if type(payload.get("code")) is int else None
                            for name in ("duration", "original_duration"):
                                value = payload.get(name)
                                entry[name] = value if finite_number(value) and value >= 0 else None
                        if entry["http_status"] != 200:
                            record_perform_error(entry, payload, key)
                            raise ValueError("音频生成返回非成功 HTTP 状态")
                        try:
                            pcm, downmixed = decode_perform(payload)
                        except (ValueError, wave.Error, EOFError):
                            record_perform_error(entry, payload, key)
                            raise
                        frames = len(pcm) // 2
                        data, reason, text_match = perform_subtitles(clip, body, payload, frames / 24000)
                        entry.update(downmixed=downmixed, text_match=text_match)
                        if payload.get("url"):
                            entry["url_expire"] = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
                    else:
                        pcm, usage, events = decode_stream(response, (lambda frame: debug_frame(frame, key)) if debug_stream else None)
                        frames = len(pcm) // 2
                        data, reason = clip_subtitles(clip, body, events, frames / 24000)
                        entry["usage"] = usage
                write_pcm_wav(audio_path, pcm)
                del pcm
                save(words_path, data)
                entry.update(status="complete", seconds=round(time.monotonic() - started, 3),
                             words_file=words_path.name, timestamps=bool(data["words"]), timestamps_reason=reason)
                save(manifest_path, manifest)
            except Exception as exc:
                if mode == "perform" and isinstance(exc, urllib.error.HTTPError):
                    try:
                        with exc:
                            logid = exc.headers.get("X-Tt-Logid") if exc.headers else None
                            entry["logid"] = logid.replace(key, "[REDACTED]") if isinstance(logid, str) else None
                            payload = json.load(exc)
                            record_perform_error(entry, payload, key)
                            if debug_stream:
                                debug_frame(payload, key)
                    except (ValueError, OSError):
                        pass
                entry.update(status="uncertain", error_type=type(exc).__name__, seconds=round(time.monotonic() - started, 3))
                save(manifest_path, manifest)
                raise RuntimeError(f"片段 {clip['id']} take {take} 结果不确定（{type(exc).__name__}）；未自动重试") from None
        cached_clips[fingerprint] = (frames, data, reason)
        selected = clip.get("perform", {}).get("selected_take") or 1
        if mode == "perform":
            alias = out / "takes" / f"{clip['id']}-take{take}.wav"
            alias.parent.mkdir(parents=True, exist_ok=True)
            temporary = alias.with_suffix(".tmp")
            shutil.copyfile(audio_path, temporary)
            temporary.replace(alias)
            takes_index.setdefault(clip["id"], []).append({
                "take": take, "fingerprint": fingerprint, "file": str(alias.relative_to(out)),
                "original_duration": entry.get("original_duration"), "text_match": entry.get("text_match")})
            if entry.get("text_match") is False:
                mismatches.append({"clip": clip["id"], "take": take})
        if take == selected:
            selection = "single" if route["takes"] == 1 else (
                "selected" if clip["perform"].get("selected_take") is not None else "provisional")
            if selection == "provisional":
                pending.append(clip["id"])
            segments.append({"clip": clip, "frames": frames, "audio": audio_path.name,
                             "words_file": words_path.name, "subtitles": data, "timestamps_reason": reason,
                             "take": take, "take_selection": selection, "text_match": entry.get("text_match"),
                             "rms_dbfs": rms_dbfs(audio_path)})
    if manifest_dirty:
        save(manifest_path, manifest)
    save(out / "takes.json", takes_index)
    result = {"clips": len(jobs), "pending_selection": pending, "text_mismatch": mismatches}
    if missing:
        # 不交付缺段或上次计划残留的 final，单段缓存和试听文件仍保留。
        for name in ("final.wav", "final.srt", "timeline.json"):
            path = out / name
            if path.is_file():
                path.unlink()
        return {**result, "audio": None, "timeline": None, "srt": None, "timestamps": False,
                "missing_clips": missing, "note": "跳过模式有片段缺少完成缓存；仅交付各段文件，不拼接 final"}
    final = out / "final.wav"
    concatenate_wavs(segments, final)
    timeline = build_timeline(segments)
    save(out / "timeline.json", timeline)
    srt = out / "final.srt"
    temp = srt.with_suffix(".tmp")
    temp.write_text(srt_text(timeline), encoding="utf-8")
    temp.replace(srt)
    return {**result, "audio": str(final.resolve()), "timestamps": timeline["timestamps"],
            "timeline": str((out / "timeline.json").resolve()), "srt": str(srt.resolve())}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--text-file", type=Path, required=True)
    prep.add_argument("--voice", default=VOICE)
    prep.add_argument("--resource-id", choices=("seed-tts-2.0", "seed-icl-2.0"))
    prep.add_argument("--pronunciation-table", type=Path,
                      help="中英发音表 JSON；快照写入计划，含英文稿默认使用随 skill 安装的表")
    prep.add_argument("--out", type=Path, required=True)
    for command in ("preview", "render"):
        cmd = sub.add_parser(command)
        cmd.add_argument("--plan", type=Path, required=True)
        cmd.add_argument("--out", type=Path, required=True)
        cmd.add_argument("--voices", type=Path, help="角色→音色 JSON；按角色覆盖计划 voices，clip 显式 voice 优先")
        if command == "render":
            cmd.add_argument("--only-mode", choices=("tts", "perform"), help="只调用指定模式；其余片段须有缓存才能拼接完整 final")
            cmd.add_argument("--dry-run", action="store_true")
            cmd.add_argument("--retry-uncertain", action="store_true")
            cmd.add_argument("--timestamps", action=argparse.BooleanOptionalAction, default=None,
                             help="启用逐字字幕（默认开启）；--no-timestamps 关闭，覆盖计划设置")
            cmd.add_argument("--debug-stream", action="store_true", help="向 stderr 输出脱敏响应帧，不输出凭据或音频数据")
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            plan = prepare(args.text_file.read_text(encoding="utf-8"), args.voice, args.resource_id,
                           load_pronunciations(args.pronunciation_table) if args.pronunciation_table else None)
            validate(plan)
            save(args.out, plan)
            result = {"plan": str(args.out.resolve())}
        else:
            plan = json.loads(args.plan.read_text(encoding="utf-8"))
            voices = json.loads(args.voices.read_text(encoding="utf-8")) if args.voices else None
            if args.voices and not isinstance(voices, dict):
                raise ValueError("voices 文件须为角色到音色 ID 的对象")
            if args.command == "preview":
                preview(plan, args.out, voices=voices)
                result = {"preview": str((args.out / "director.html").resolve())}
            else:
                result = render(plan, args.out, args.dry_run, args.retry_uncertain, args.timestamps, args.debug_stream,
                                voices=voices, only_mode=args.only_mode)
        print(json.dumps(result, ensure_ascii=False))
    except (ValueError, RuntimeError, OSError, KeyError, TypeError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
