#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["pypinyin==0.55.0"]
# ///
"""中文校对、阅读稿和火山 TTS；preview/prepare/dry-run 均不访问网络。"""
import argparse
import base64
import hashlib
import html
import io
import json
import os
import re
import sys
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
VOICE = "zh_female_vv_uranus_bigtts"
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
    if not isinstance(text, str) or not HAN.search(text):
        raise ValueError("稿件必须包含中文")
    if any(c.isalpha() and not HAN.fullmatch(c) for c in text):
        raise ValueError("只做中文；请先明确外文或缩写的中文口播方式")


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


def readings(clip, complete=False):
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
        if not 1 <= len(word) <= 9 or any(not (HAN.fullmatch(c) or c.isdecimal()) for c in word) or word in seen:
            raise ValueError("字典原词须为 1～9 个中文或数字字符，且不可重复")
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
    if len(rules) > 5000:
        raise ValueError("发音字典最多 5000 个词条")
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
                               for c in value]
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


def resolve_resource(clip):
    voice = clip["voice"]
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
    # 预置资源保留旧指纹，避免丢失完成缓存或绕过 uncertain。
    value = body if resource == "seed-tts-2.0" else {
        "endpoint": ENDPOINT, "resource_id": resource, "body": body}
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def validate(plan, complete=False):
    clips = plan.get("clips")
    if not isinstance(clips, list) or not clips:
        raise ValueError("计划需要非空 clips")
    ids = set()
    for clip in clips:
        ident = clip["id"]
        if not isinstance(ident, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", ident) or ident in ids:
            raise ValueError("片段 id 必须唯一且只包含字母数字下划线短横线")
        ids.add(ident)
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
        readings(clip, complete)


def prepare(text, voice=VOICE, resource_id=None):
    selection = {"voice": voice}
    if resource_id is not None:
        selection["resource_id"] = resource_id
    resource = resolve_resource(selection)
    check_text(text)
    # ponytail: 500 字保守本地上限；需要更长连续朗读时核实账号与模型限制后调整。
    parts, current = [], ""
    for sentence in re.findall(r"[^。！？\n]*[。！？\n]|[^。！？\n]+$", text):
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
    if resource_id is not None or resource == "seed-icl-2.0":
        for clip in clips:
            clip["resource_id"] = resource
    return {"title": "中文阅读", "clips": clips}


def preview(plan, out):
    validate(plan)
    out.mkdir(parents=True, exist_ok=True)
    title = str(plan.get("title", "中文阅读"))
    md, sections = [f"# {title}\n\n读音为校对标注，不进入口播。待校对项尚未确定。\n"], []
    for clip in plan["clips"]:
        rows, _ = readings(clip)
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
                    ("补充发音字典", "\n".join(clip.get("pronunciation_dict", {}).get("tone", [])))]
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
<title>中文阅读稿</title><style>body{max-width:1040px;margin:40px auto;padding:0 24px;color:#203038;background:#f7f5ef;font-family:system-ui,sans-serif}section{background:white;border:1px solid #deded5;border-radius:12px;padding:24px;margin:24px 0}h2{font-size:15px;color:#526369}.script{font-size:23px;line-height:2.5;white-space:pre-wrap}ruby.reviewed{background:#e3f1e9}ruby.pending{background:#ffe8b4}rt{font-size:12px;color:#435d59}table{border-collapse:collapse;width:100%;font-size:13px}td,th{text-align:left;padding:10px;border-bottom:1px solid #eee}.table{overflow:auto}button{padding:8px 16px;cursor:pointer}.hide rt{visibility:hidden}@media(max-width:600px){body{padding:0 12px}section{padding:16px}}</style>
<h1>''' + html.escape(title) + '''</h1><p>中文阅读稿 · 黄色待校对，绿色已校对。注音与导演说明不进入口播。本页不证明已生成音频。</p>
<button onclick="document.body.classList.toggle('hide')">显示／隐藏注音</button>''' + "".join(sections) + "</html>"
    (out / "director.html").write_text(page, encoding="utf-8")


def request_body(clip):
    rows, rules = readings(clip, complete=True)
    text, instructions = list(clip["text"]), []
    additions = {"disable_markdown_filter": True}
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
    for row in rows:
        delivery = row.get("delivery", "spoken_alias" if "spoken_alias" in row else "dictionary")
        if delivery == "spoken_alias":
            start = row["start"]
            text[start:start + len(row["text"])] = row["spoken_alias"]
        if delivery in ("instruction", "spoken_alias"):
            target = row.get("spoken_alias", row["text"])
            instructions.append(f'发音要求：原文“{row["text"]}”，本次提交的“{target}”读作 {" ".join(row["pinyin"])}。')
    if instructions:
        # 全部说明合入首条，避免后续指令被忽略。
        additions["context_texts"] = ["\n".join(instructions)]
    return {"req_params": {"text": "".join(text), "speaker": clip["voice"],
            "audio_params": {"format": "pcm", "sample_rate": 24000,
                             "speech_rate": clip.get("speech_rate", 0)},
            "additions": json.dumps(additions, ensure_ascii=False)}}


def decode_stream(lines):
    audio, usage, finished = bytearray(), None, False
    for line in lines:
        if not line.strip():
            continue
        frame = json.loads(line)
        code = frame.get("code")
        if code not in (0, 20000000):
            raise RuntimeError(f"火山返回错误码 {code}")
        if frame.get("data"):
            audio.extend(base64.b64decode(frame["data"], validate=True))
        if frame.get("usage") is not None:
            usage = frame["usage"]
        if code == 20000000:
            finished = True
            break
    if not finished or not audio or len(audio) % 2:
        raise RuntimeError("音频流未完整结束或 PCM 数据无效")
    return bytes(audio), usage


def wav_bytes(pcm):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(pcm)
    return buffer.getvalue()


def render(plan, out, dry_run=False, retry_uncertain=False):
    validate(plan, complete=True)
    jobs = [(clip, request_body(clip), resolve_resource(clip)) for clip in plan["clips"]]
    routes = [{"clip": clip["id"], "speaker": clip["voice"], "resource_id": resource,
               "endpoint": ENDPOINT} for clip, _, resource in jobs]
    out.mkdir(parents=True, exist_ok=True)
    save(out / "requests.json", [body for _, body, _ in jobs])
    save(out / "routes.json", routes)
    if dry_run:
        return {"dry_run": True, "clips": len(jobs),
                "characters": sum(len(c["text"]) for c, _, _ in jobs), "routes": routes}
    key = os.environ.get("VOLC_TTS_API_KEY")
    if not key:
        raise ValueError("运行环境缺少 VOLC_TTS_API_KEY")
    manifest_path = out / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    fingerprints = [request_fingerprint(body, resource) for _, body, resource in jobs]
    for _, body, resource in jobs:
        if resource != "seed-tts-2.0" and request_fingerprint(body, "seed-tts-2.0") in manifest:
            raise RuntimeError("已有未绑定资源的旧克隆请求记录；请先核对服务记录，不自动复用或重发")
    if not retry_uncertain and any(manifest.get(f, {}).get("status") == "uncertain" for f in fingerprints):
        raise RuntimeError("已有结果不确定的请求；核对服务记录与授权后才能 --retry-uncertain")
    pcm_all = bytearray()
    for (clip, body, resource), fingerprint in zip(jobs, fingerprints):
        audio_path = out / (fingerprint + ".wav")
        entry = manifest.get(fingerprint, {})
        if entry.get("status") == "complete":
            with wave.open(str(audio_path), "rb") as wav:
                if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, 24000):
                    raise ValueError("缓存音频格式错误")
                pcm = wav.readframes(wav.getnframes())
                if not pcm:
                    raise ValueError("缓存音频为空")
        else:
            request_id = str(uuid.uuid4())
            entry = {"status": "uncertain", "request_id": request_id, "clip": clip["id"],
                     "resource_id": resource, "endpoint": ENDPOINT}
            manifest[fingerprint] = entry
            save(manifest_path, manifest)
            request = urllib.request.Request(ENDPOINT, data=json.dumps(body, ensure_ascii=False).encode(),
                headers={"Content-Type": "application/json", "X-Api-Key": key,
                         "X-Api-Resource-Id": resource, "X-Api-Request-Id": request_id}, method="POST")
            started = time.monotonic()
            try:
                # 不跟随重定向，避免凭据转发到另一目的地。
                opener = urllib.request.build_opener(NoRedirect)
                with opener.open(request, timeout=90) as response:
                    entry["logid"] = response.headers.get("X-Tt-Logid")
                    pcm, usage = decode_stream(response)
                temp = audio_path.with_suffix(".tmp")
                temp.write_bytes(wav_bytes(pcm))
                temp.replace(audio_path)
                entry.update(status="complete", usage=usage, seconds=round(time.monotonic() - started, 3))
                save(manifest_path, manifest)
            except Exception as exc:
                entry.update(error_type=type(exc).__name__, seconds=round(time.monotonic() - started, 3))
                save(manifest_path, manifest)
                raise RuntimeError(f"片段 {clip['id']} 结果不确定（{type(exc).__name__}）；未自动重试") from None
        pcm_all.extend(pcm)
        pcm_all.extend(b"\0\0" * (24 * clip.get("pause_after_ms", 0)))
    final = out / "final.wav"
    temp = final.with_suffix(".tmp")
    temp.write_bytes(wav_bytes(pcm_all))
    temp.replace(final)
    return {"audio": str(final.resolve()), "clips": len(jobs)}


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
    prep.add_argument("--out", type=Path, required=True)
    for command in ("preview", "render"):
        cmd = sub.add_parser(command)
        cmd.add_argument("--plan", type=Path, required=True)
        cmd.add_argument("--out", type=Path, required=True)
        if command == "render":
            cmd.add_argument("--dry-run", action="store_true")
            cmd.add_argument("--retry-uncertain", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            plan = prepare(args.text_file.read_text(encoding="utf-8"), args.voice, args.resource_id)
            validate(plan)
            save(args.out, plan)
            result = {"plan": str(args.out.resolve())}
        else:
            plan = json.loads(args.plan.read_text(encoding="utf-8"))
            if args.command == "preview":
                preview(plan, args.out)
                result = {"preview": str((args.out / "director.html").resolve())}
            else:
                result = render(plan, args.out, args.dry_run, args.retry_uncertain)
        print(json.dumps(result, ensure_ascii=False))
    except (ValueError, RuntimeError, OSError, KeyError, TypeError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
