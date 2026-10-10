"""本地验收：真实中文校对 + 请求接线 + 模拟音频；零 TTS 调用。"""
import base64
import copy
import hashlib
import importlib.util
import io
import json
import os
import tempfile
import uuid
import wave
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("tts", ROOT / "skills/volce-tts-director/scripts/tts.py")
tts = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tts)


def fails(call, message):
    try:
        call()
    except (ValueError, RuntimeError):
        return
    raise AssertionError(message)


def clone_checks(plan, frames, pcm):
    clone = copy.deepcopy(plan)
    clone["clips"] = clone["clips"][:1]
    clip = clone["clips"][0]
    clip.update(voice="S_xWSg2NNT1", direction="")
    tts.validate(clone, True)
    assert tts.resolve_resource(clip) == "seed-icl-2.0"
    body = tts.request_body(clip)
    assert body["req_params"]["speaker"] == "S_xWSg2NNT1"
    assert isinstance(body["req_params"]["additions"], str)
    assert "context_texts" not in json.loads(body["req_params"]["additions"])
    draft = tts.prepare("你好。", voice=clip["voice"])
    assert draft["clips"][0]["resource_id"] == "seed-icl-2.0"
    assert draft["clips"][0]["direction"] == ""
    assert tts.prepare("你好。", clip["voice"], "seed-icl-2.0") == draft
    assert tts.prepare("你好。")["clips"][0]["direction"] == "自然、清楚的普通话朗读"
    for voice in ("S_", "S_xWSg2NNT1/", "S_x WSg2NNT1", "en_voice", "", None, 123):
        bad = copy.deepcopy(clone)
        bad["clips"][0]["voice"] = voice
        fails(lambda: tts.validate(bad), "拒绝非法音色")
    for resource in ("seed-tts-2.0", "seed-icl-1.0", "", None, []):
        bad = copy.deepcopy(clone)
        bad["clips"][0]["resource_id"] = resource
        fails(lambda: tts.validate(bad), "拒绝克隆资源错配或未知代际")
    fails(lambda: tts.prepare("你好。", resource_id="seed-icl-2.0"), "拒绝预置资源错配")
    expected = ["seed-tts-2.0", "seed-icl-2.0"]
    mixed = {"clips": [copy.deepcopy(plan["clips"][0]), copy.deepcopy(clip)]}
    mixed["clips"][1]["id"] = "clone"
    seen = []
    class Response(io.BytesIO):
        headers = {"X-Tt-Logid": "offline-clone"}
    class Opener:
        def open(self, request, timeout):
            resource = request.get_header("X-api-resource-id")
            sent = json.loads(request.data)["req_params"]
            assert resource == ("seed-icl-2.0" if sent["speaker"].startswith("S_") else "seed-tts-2.0")
            assert request.get_header("X-api-key") == "offline-fake-key"
            assert request.full_url == tts.ENDPOINT and request.method == "POST"
            assert str(uuid.UUID(request.get_header("X-api-request-id"))) == request.get_header("X-api-request-id")
            seen.append(resource)
            return Response(b"\n".join(frames))
    with tempfile.TemporaryDirectory(prefix="volce-clone-check-") as directory:
        out = Path(directory)
        with patch.dict(os.environ, {}, clear=True), patch.object(
                tts.urllib.request, "build_opener", side_effect=AssertionError("dry-run 不能联网")):
            summary = tts.render(mixed, out / "audio", dry_run=True)
            assert [r["resource_id"] for r in summary["routes"]] == expected
            assert summary["routes"][1]["speaker"] == clip["voice"]
            saved = json.loads((out / "audio/requests.json").read_text())
            assert saved == [tts.request_body(c) for c in mixed["clips"]]
            assert json.loads((out / "audio/routes.json").read_text()) == summary["routes"]
            fails(lambda: tts.render(clone, out / "missing-key"), "真实合成必须有密钥")
        tts.preview(clone, out / "preview")
        assert "seed-icl-2.0" in (out / "preview/director.html").read_text()
        preset_body = tts.request_body(mixed["clips"][0])
        legacy = hashlib.sha256(json.dumps(preset_body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        assert tts.request_fingerprint(preset_body, "seed-tts-2.0") == legacy
        legacy_out = out / "legacy"
        tts.save(legacy_out / "manifest.json", {legacy: {"status": "complete"}})
        (legacy_out / (legacy + ".wav")).write_bytes(tts.wav_bytes(pcm))
        tts.save(legacy_out / (legacy + ".words.json"), {"text": mixed["clips"][0]["text"], "words": []})
        preset = {"clips": [copy.deepcopy(mixed["clips"][0])]}
        with patch.dict(os.environ, {"VOLC_TTS_API_KEY": "offline-fake-key"}, clear=True), patch.object(
                tts.urllib.request, "build_opener", return_value=Opener()) as network:
            tts.render(preset, legacy_out)
            preset["clips"][0]["resource_id"] = "seed-tts-2.0"
            tts.render(preset, legacy_out)
            assert network.call_count == 0, "显式默认资源与旧缓存兼容"
            tts.render(mixed, out / "audio")
            assert seen == expected and network.call_count == 2
            explicit = copy.deepcopy(mixed)
            explicit["clips"][1]["resource_id"] = "seed-icl-2.0"
            explicit["clips"][1]["pause_after_ms"] = 500
            tts.render(explicit, out / "audio")
            assert network.call_count == 2, "克隆默认/显式资源、停顿调整复用缓存"
            assert tts.request_fingerprint(body, "seed-icl-2.0") != tts.request_fingerprint(body, "seed-tts-2.0")
            tts.save(out / "blocked/manifest.json", {legacy: {"status": "uncertain"}})
            fails(lambda: tts.render({"clips": list(reversed(mixed["clips"]))}, out / "blocked"),
                  "旧 uncertain 必须在任何新调用前阻断")
            assert network.call_count == 2
            for status in ("complete", "uncertain"):
                clone_legacy = tts.request_fingerprint(body, "seed-tts-2.0")
                tts.save(out / "ambiguous/manifest.json", {clone_legacy: {"status": status}})
                fails(lambda: tts.render(clone, out / "ambiguous", retry_uncertain=True),
                      "来源不明的旧克隆记录不能复用或静默绕过")
            assert network.call_count == 2
            changed = copy.deepcopy(mixed)
            changed["clips"][1]["direction"] = "轻声叙述。"
            tts.render(changed, out / "audio")
            assert network.call_count == 3, "只重做克隆音色受影响段"
            broken = out / "broken"
            with patch.object(tts.urllib.request, "build_opener", side_effect=OSError("模拟断网")):
                fails(lambda: tts.render(clone, broken), "克隆断网也要停止")
            fails(lambda: tts.render(clone, broken), "克隆 uncertain 不自动重发")
            assert network.call_count == 3
            entries = json.loads((broken / "manifest.json").read_text())
            assert all(e["status"] == "uncertain" and e["resource_id"] == "seed-icl-2.0" for e in entries.values())
        assert all("offline-fake-key" not in f.read_text() for f in out.rglob("*.json"))
        assert tts.NoRedirect().redirect_request(None, None, 302, "", {}, "https://example.com") is None


def timestamp_checks():
    plan = tts.prepare("你好。再见！")
    clip = plan["clips"][0]
    for row in clip["readings"]:
        assert row["text"] in ("好", "见")
        row.update(status="reviewed", pinyin=[{"好": "hao3", "见": "jian4"}[row["text"]]])
    clip["pause_after_ms"] = 375
    second = copy.deepcopy(clip)
    second.update(id="second", pause_after_ms=125)
    plan["clips"].append(second)
    pcm = b"\x01\x00" * 48000
    first_sentence = {"text": "你好。", "phonemes": [], "words": [
        {"word": "你", "startTime": 0.1, "endTime": 0.4, "confidence": 0.95},
        {"word": "好。", "startTime": 0.4, "endTime": 0.8, "confidence": 0.96}]}
    last_sentence = {"text": "再见！", "words": [
        {"word": "再", "startTime": 1.1, "endTime": 1.4, "confidence": 0.95},
        {"word": "见！", "startTime": 1.4, "endTime": 1.8, "confidence": 0.96}]}
    events = [first_sentence, last_sentence]
    def line(frame):
        return json.dumps(frame, ensure_ascii=False).encode()
    frames = [line({"code": 0, "data": base64.b64encode(pcm[:48000]).decode(), "sentence": first_sentence}),
              line({"code": 0, "data": base64.b64encode(pcm[48000:]).decode()}),
              b"\n", line({"code": 0, "data": None, "sentence": last_sentence}),
              line({"code": 20000000, "message": "OK", "usage": {"text_words": 4}})]
    debug = []
    assert tts.decode_stream(frames, debug.append) == (pcm, {"text_words": 4}, events)
    assert len(debug) == 4 and debug[-2]["sentence"] == last_sentence, "收集最后音频之后的字幕"
    terminal = frames[:-2] + [line({"code": 20000000, "sentence": last_sentence})]
    assert tts.decode_stream(terminal)[2] == events, "完成帧携带的字幕也不能丢"
    # 防御性测试：不把完成码后的额外字幕当作官方正常帧序，但也不静默截断。
    after_terminal = frames[:2] + [line({"code": 20000000}), frames[-2]]
    assert tts.decode_stream(after_terminal)[2] == events
    fails(lambda: tts.decode_stream(frames[:-1]), "有完整字幕但无完成码仍失败")
    data = tts.subtitle_data(events + [last_sentence], clip["text"])
    assert data["text"] == clip["text"] and len(data["words"]) == 4
    assert data["sentences"] == [
        {"text": "你好。", "startTime": 0.1, "endTime": 0.8},
        {"text": "再见！", "startTime": 1.1, "endTime": 1.8}]
    cumulative = copy.deepcopy(first_sentence)
    cumulative["words"] = cumulative["words"][:1]
    assert tts.subtitle_data([cumulative, first_sentence], "你好。")["text"] == "你好。"
    assert len(tts.subtitle_data([first_sentence, first_sentence], "你好。")["words"]) == 2
    paragraph = {"text": clip["text"], "words": data["words"]}
    assert tts.subtitle_data([paragraph], clip["text"])["sentences"] == data["sentences"], "一个字幕帧按句分 SRT"
    quoted = {"text": "“你好。”\n再见！", "words": data["words"]}
    assert [cue["text"] for cue in tts.subtitle_data([quoted], quoted["text"])["sentences"]] == ["“你好。”", "再见！"]
    assert tts.subtitle_data([{"text": clip["text"], "words": [], "phonemes": []}] + events,
                             clip["text"])["text"] == clip["text"], "空字幕预告帧不能重复正文"
    whole = {"text": "你好。再见！大家好。", "words": data["words"] + [
        {"word": "大", "startTime": 2.2, "endTime": 2.4},
        {"word": "家", "startTime": 2.4, "endTime": 2.6},
        {"word": "好。", "startTime": 2.6, "endTime": 2.9}]}
    merged = tts.subtitle_data(events + [whole], whole["text"])
    assert merged["text"] == whole["text"] and len(merged["sentences"]) == 3
    revised = {**first_sentence, "text": "你好！"}
    assert tts.subtitle_data([first_sentence, revised], "你好。")["text"] == "你好！", "同时间字词的标点修订要保留"
    assert tts.clip_subtitles(clip, tts.request_body(clip), events, 0.1)[1] == "invalid_subtitles"
    assert tts.sentence_cues("编号123。", [{"word": "一百二十三", "startTime": 0.2, "endTime": 1.2}]) == [
        {"text": "编号123。", "startTime": 0.2, "endTime": 1.2}], "文本规范化不能猜逐字时间"
    enabled = tts.request_body(clip)
    disabled = tts.request_body(clip, False)
    assert enabled["req_params"]["audio_params"]["enable_subtitle"] is True
    assert "enable_timestamp" not in json.dumps(enabled)
    legacy = copy.deepcopy(enabled)
    del legacy["req_params"]["audio_params"]["enable_subtitle"]
    for resource in ("seed-tts-2.0", "seed-icl-2.0"):
        assert len({tts.request_fingerprint(body, resource) for body in (enabled, disabled, legacy)}) == 3
    for value in ("true", 1, None):
        bad = copy.deepcopy(plan)
        bad["enable_subtitle"] = value
        fails(lambda: tts.validate(bad), "计划字幕开关必须为布尔值")
        for name in ("enable_subtitle", "enable_latex_tn"):
            bad = copy.deepcopy(plan)
            bad["clips"][0][name] = value
            fails(lambda: tts.validate(bad), "片段字幕/LaTeX 开关必须为布尔值")
    for name, value, reason in (("explicit_dialect", "beijing", "explicit_dialect"),
                               ("enable_latex_tn", True, "enable_latex_tn"),
                               ("enable_subtitle", False, "disabled")):
        downgraded = copy.deepcopy(clip)
        downgraded[name] = value
        body = tts.request_body(downgraded)
        assert body["req_params"]["audio_params"]["enable_subtitle"] is False
        if name == "enable_latex_tn":
            assert json.loads(body["req_params"]["additions"])[name] is True
        result, cause = tts.clip_subtitles(downgraded, body, events)
        assert not result["words"] and cause == reason
    assert tts.clip_subtitles(clip, enabled, [])[1] == "not_returned"
    assert tts.clip_subtitles(clip, enabled, [{"text": clip["text"], "words": [], "phonemes": []}])[1] == "not_returned"
    for start, end in ((-1, 0), (1, 0), (float("nan"), 1), (0, float("inf")), ("0", 1)):
        bad_event = copy.deepcopy(first_sentence)
        bad_event["words"][0].update(startTime=start, endTime=end)
        assert tts.clip_subtitles(clip, enabled, [bad_event])[1] == "invalid_subtitles"
    secret = "offline-subtitle-secret"
    logs = io.StringIO()
    with redirect_stderr(logs):
        tts.debug_frame({"code": 0, "data": "AAAA", "sentence": first_sentence,
                         "X-Api-Key": secret, "message": "echo " + secret,
                         "nested": {secret: [secret], "token": "another-secret"}}, secret)
    assert secret not in logs.getvalue() and "another-secret" not in logs.getvalue()
    assert "sentence" in logs.getvalue() and "AAAA" not in logs.getvalue()
    class Response(io.BytesIO):
        headers = {"X-Tt-Logid": "offline-subtitles"}
    class Opener:
        def open(self, request, timeout):
            assert json.loads(request.data)["req_params"]["audio_params"]["enable_subtitle"] is True
            return Response(b"\n".join(frames))
    with tempfile.TemporaryDirectory(prefix="volce-timestamps-check-") as directory:
        out = Path(directory)
        switched = copy.deepcopy(plan)
        switched["enable_subtitle"] = False
        switched["clips"][0]["enable_subtitle"] = True
        with patch.dict(os.environ, {}, clear=True), patch.object(
                tts.urllib.request, "build_opener", side_effect=AssertionError("dry-run 不能联网")):
            tts.render(switched, out / "dry", dry_run=True, debug_stream=True)
            requests = json.loads((out / "dry/requests.json").read_text())
            assert [r["req_params"]["audio_params"]["enable_subtitle"] for r in requests] == [True, False]
            for flag in (True, False):
                tts.render(switched, out / "dry", dry_run=True, timestamps=flag)
                assert all(r["req_params"]["audio_params"]["enable_subtitle"] is flag
                           for r in json.loads((out / "dry/requests.json").read_text()))
            assert not list((out / "dry").glob("*.wav")) and not (out / "dry/timeline.json").exists()
            for flag in ("--timestamps", "--no-timestamps"):
                with patch("sys.argv", ["tts.py", "render", "--plan", str(out / "cli.json"),
                                         "--out", str(out / "cli"), "--dry-run", flag]), redirect_stdout(io.StringIO()):
                    tts.save(out / "cli.json", switched)
                    assert tts.main() == 0
                    assert all(r["req_params"]["audio_params"]["enable_subtitle"] is (flag == "--timestamps")
                               for r in json.loads((out / "cli/requests.json").read_text()))
        with patch.dict(os.environ, {"VOLC_TTS_API_KEY": secret}, clear=True), patch.object(
                tts.urllib.request, "build_opener", return_value=Opener()) as network:
            rendered = tts.render(plan, out / "audio")
            assert network.call_count == 1, "同请求不同 clip ID 与停顿复用音频与字幕"
            assert rendered["timestamps"] is True
            timeline = json.loads((out / "audio/timeline.json").read_text())
            assert timeline["duration"] == 4.5
            assert [c["offset"] for c in timeline["clips"]] == [0, 2.375]
            assert timeline["words"][4]["startTime"] == 2.475
            assert timeline["words"][-1]["endTime"] == 4.175
            assert timeline["sentences"][2]["text"] == "你好。"
            assert "3\n00:00:02,475 --> 00:00:03,175\n你好。" in (out / "audio/final.srt").read_text()
            with wave.open(str(out / "audio/final.wav")) as wav:
                assert wav.getnframes() == 108000
            fingerprint = tts.request_fingerprint(enabled, "seed-tts-2.0")
            sidecar = out / "audio" / (fingerprint + ".words.json")
            assert json.loads(sidecar.read_text()) == data
            entry = json.loads((out / "audio/manifest.json").read_text())[fingerprint]
            assert entry["timestamps"] is True and entry["words_file"] == sidecar.name
            assert tts.render(plan, out / "audio") == rendered and network.call_count == 1
            changed = copy.deepcopy(plan)
            changed["clips"][0]["pause_after_ms"] = 1000
            tts.render(changed, out / "audio")
            updated = json.loads((out / "audio/timeline.json").read_text())
            assert updated["clips"][1]["offset"] == 3 and updated["words"][4]["startTime"] == 3.1
            assert network.call_count == 1
            normalized = copy.deepcopy(data)
            normalized["words"] = list(reversed(normalized["words"])) + [normalized["words"][0]]
            tts.save(sidecar, normalized)
            tts.render(plan, out / "audio")
            assert json.loads((out / "audio/timeline.json").read_text())["words"][:4] == timeline["words"][:4]
            new_first = copy.deepcopy(plan)
            new_first["clips"][0]["direction"] = "低声叙述。"
            invalid_cues = copy.deepcopy(data)
            invalid_cues["sentences"][0].update(text="无关旧句子", startTime=-2, endTime=90)
            invalid_words = copy.deepcopy(data)
            invalid_words["words"][-1]["endTime"] = 90
            stale_text = copy.deepcopy(data)
            stale_text["sentences"][0]["text"] = "无关旧句子"
            for content in ("{", "[]", json.dumps(invalid_cues), json.dumps(invalid_words),
                            json.dumps(stale_text), '{"text":"你好。"}'):
                sidecar.write_text(content)
                fails(lambda: tts.render(new_first, out / "audio"), "损坏缓存必须在任何新调用前校验")
                assert network.call_count == 1
            tts.save(sidecar, data)
            # 丢失新缓存 sidecar，或遇到未带字幕开关的旧缓存，均在任何调用之前阻断。
            sidecar.unlink()
            for cached in (fingerprint, tts.request_fingerprint(legacy, "seed-tts-2.0")):
                tts.save(out / "missing/manifest.json", {cached: {"status": "complete"}})
                try:
                    tts.render(new_first, out / "missing")
                except RuntimeError as exc:
                    assert "需要重新渲染" in str(exc) and "未自动重发" in str(exc)
                else:
                    raise AssertionError("缺字幕缓存不能静默复用或重发")
                assert network.call_count == 1
            fails(lambda: tts.render(plan, out / "audio"), "缺失字幕 sidecar 应阻断缓存命中")
            old_fingerprint = tts.request_fingerprint(legacy, "seed-tts-2.0")
            tts.save(out / "uncertain/manifest.json", {old_fingerprint: {"status": "uncertain"}})
            fails(lambda: tts.render(new_first, out / "uncertain"), "新增字幕字段不能绕过旧 uncertain")
            assert network.call_count == 1
            no_subtitles = [frames[1], frames[-1]]
            with patch.object(tts.urllib.request, "build_opener") as fallback_network:
                fallback_network.return_value.open.side_effect = lambda *args, **kwargs: Response(b"\n".join(no_subtitles))
                tts.render(plan, out / "fallback")
                tts.render(plan, out / "fallback")
                assert fallback_network.return_value.open.call_count == 1, "无字幕也缓存，不反复计费"
                entries = json.loads((out / "fallback/manifest.json").read_text())
                assert all(e["timestamps"] is False and e["timestamps_reason"] == "not_returned" for e in entries.values())
                assert (out / "fallback/final.srt").read_text() == ""
                fallback = json.loads((out / "fallback/timeline.json").read_text())
                assert fallback["timestamps"] is False and fallback["words"] == []
                mixed = copy.deepcopy(plan)
                mixed["clips"][1]["explicit_dialect"] = "beijing"
                tts.render(mixed, out / "mixed")
                statuses = list(json.loads((out / "mixed/manifest.json").read_text()).values())
                assert any(e["timestamps_reason"] == "explicit_dialect" for e in statuses)
                for controls, reason in (({}, "invalid_subtitles"), ({"enable_latex_tn": True}, "enable_latex_tn")):
                    short_plan = copy.deepcopy(plan)
                    short_plan["clips"][0].update(controls)
                    short_plan["clips"] = short_plan["clips"][:1]
                    short_stream = [line({"code": 0, "data": base64.b64encode(pcm[:4800]).decode(),
                                          "sentence": first_sentence}), frames[-1]]
                    fallback_network.return_value.open.side_effect = lambda *args, **kwargs: Response(b"\n".join(short_stream))
                    tts.render(short_plan, out / reason)
                    entry = next(iter(json.loads((out / reason / "manifest.json").read_text()).values()))
                    assert entry["timestamps"] is False and entry["timestamps_reason"] == reason
                    assert (out / reason / "final.srt").read_text() == ""
        assert all(secret not in f.read_text() for f in out.rglob("*.json"))
    empty = {"text": "你好。", "words": [], "sentences": []}
    precise = tts.build_timeline([
        {"clip": {"id": "tiny", "text": "你好。", "pause_after_ms": 1}, "frames": 24001,
         "audio": "tiny.wav", "words_file": "tiny.words.json", "subtitles": empty, "timestamps_reason": "disabled"},
        {"clip": {"id": "next", "text": "你好。"}, "frames": 7,
         "audio": "next.wav", "words_file": "next.words.json", "subtitles": empty, "timestamps_reason": "disabled"}])
    assert precise["clips"][1]["offset"] == 24025 / 24000
    assert precise["duration"] == 24032 / 24000, "偏移不能将 PCM 时长提前舍入到毫秒"


def timestamp_review_checks():
    """十项评审回归；全部事件/WAV/缓存均为合成夹具，不是线上协议证据。"""
    fake_key = "offline-timestamp-review-key"

    def word(text, start, end):
        return {"word": text, "startTime": start, "endTime": end}

    def cue(text, start, end):
        return {"text": text, "startTime": start, "endTime": end}

    def reviewed_plan(text="你好。再见！"):
        plan = tts.prepare(text)
        for clip in plan["clips"]:
            for row in clip["readings"]:
                row["status"] = "reviewed"
        tts.validate(plan, complete=True)
        return plan

    base_plan = reviewed_plan()
    base_words = [word("你", .1, .4), word("好。", .4, .8),
                  word("再", 1.1, 1.4), word("见！", 1.4, 1.8)]
    base_data = {"text": "你好。再见！", "words": base_words,
                 "sentences": [cue("你好。", .1, .8), cue("再见！", 1.1, 1.8)]}
    pcm = b"\x01\x00" * 48000

    class Response(io.BytesIO):
        headers = {"X-Tt-Logid": "offline-timestamp-review"}

    def stream(events, audio=pcm):
        frames = [{"code": 0, "data": base64.b64encode(audio).decode()}]
        frames.extend({"code": 0, "sentence": event} for event in events)
        frames.append({"code": 20000000, "usage": {"text_words": 4}})
        return b"\n".join(json.dumps(frame, ensure_ascii=False).encode() for frame in frames)

    def fingerprint(clip):
        return tts.request_fingerprint(tts.request_body(clip), tts.resolve_resource(clip))

    def cached(directory, plan=base_plan, data=base_data, frames=48000, metadata=True):
        directory.mkdir(parents=True, exist_ok=True)
        manifest = {}
        for index, clip in enumerate(plan["clips"]):
            fp = fingerprint(clip)
            # 不同缓存文件使用不同 PCM，避免拼接顺序错误被全静音夹具掩盖。
            audio = bytes((index + 1, 0)) * frames
            (directory / (fp + ".wav")).write_bytes(tts.wav_bytes(audio))
            tts.save(directory / (fp + ".words.json"), data)
            entry = {"status": "complete"}
            if metadata:
                entry.update(words_file=fp + ".words.json", timestamps=bool(data["words"]),
                             timestamps_reason="" if data["words"] else "not_returned")
            manifest[fp] = entry
        tts.save(directory / "manifest.json", manifest)
        return manifest

    def new_before_cached(plan):
        mixed = copy.deepcopy(plan)
        new = copy.deepcopy(plan["clips"][0])
        new.update(id="new-before-cache", direction="低声清楚地说。")
        mixed["clips"].insert(0, new)
        return mixed

    def cache_rejected(plan, directory):
        with patch.object(tts.urllib.request, "build_opener",
                          side_effect=AssertionError("损坏后段缓存之前不得发出新请求")) as network:
            try:
                tts.render(new_before_cached(plan), directory)
            except RuntimeError as exc:
                assert "需要重新渲染" in str(exc) and "未自动重发" in str(exc), str(exc)
            else:
                raise AssertionError("无效缓存必须友好拒绝，不得复用")
            assert network.call_count == 0, "缓存预检必须先于任何新请求"

    def fresh_invalid(plan, events, directory):
        with patch.object(tts.urllib.request, "build_opener") as network:
            network.return_value.open.return_value = Response(stream(events))
            result = tts.render(plan, directory)
            assert network.call_count == 1
        entry = json.loads((directory / "manifest.json").read_text())[fingerprint(plan["clips"][0])]
        assert entry["status"] == "complete", "字幕错误不能令完整音频变 uncertain"
        assert entry["timestamps"] is False and entry["timestamps_reason"] == "invalid_subtitles"
        assert result["timestamps"] is False and (directory / "final.srt").read_text() == ""
        data = json.loads((directory / entry["words_file"]).read_text())
        assert data == {"text": tts.request_body(plan["clips"][0])["req_params"]["text"],
                        "words": [], "sentences": []}
        with wave.open(str(directory / "final.wav"), "rb") as wav:
            assert wav.getnframes() == len(pcm) // 2 and wav.readframes(48000) == pcm

    def public_data(data):
        assert set(data) == {"text", "words", "sentences"}
        assert all(set(item) == {"text", "startTime", "endTime"} for item in data["sentences"])
        assert all(set(item) <= {"word", "startTime", "endTime", "confidence"} for item in data["words"])

    def huge_json_numbers(directory):
        huge = json.loads("1" + "0" * 399)
        assert huge == 10 ** 399, "必须覆盖 JSON 可解析、但不能转换为 float 的整数"
        for field in ("startTime", "endTime", "confidence"):
            bad = copy.deepcopy(base_data)
            bad["words"][0][field] = huge
            fresh_invalid(base_plan, [bad], directory / ("fresh-" + field))
            out = directory / ("cache-word-" + field)
            cached(out, data=bad)
            cache_rejected(base_plan, out)
        for field in ("startTime", "endTime"):
            bad = copy.deepcopy(base_data)
            bad["sentences"][0][field] = huge
            out = directory / ("cache-cue-" + field)
            cached(out, data=bad)
            cache_rejected(base_plan, out)

    def cumulative_revisions(directory):
        first = {"text": "你好", "words": [word("你", .1, .4), word("好", .4, .8)]}
        variants = [
            {"text": "你好。", "words": [word("你", .1, .4), word("好。", .4, .8)]},
            {"text": "你好。", "words": [word("你", .1, .4), word("好。", .4, .85)]},
            {"text": "你好。", "words": [word("你", .11, .41), word("好。", .41, .86)]}]
        for revised in variants:
            data = tts.subtitle_data([first, revised, revised], "你好。", 2)
            assert data == {"text": revised["text"], "words": revised["words"],
                            "sentences": [cue("你好。", revised["words"][0]["startTime"],
                                              revised["words"][-1]["endTime"])]}, "只保留最新累计帧，不能残留旧三元组"
            public_data(data)
        old_punctuation = {"text": "你好！", "words": variants[0]["words"]}
        assert tts.subtitle_data([variants[0], old_punctuation], "你好。") == {
            "text": "你好！", "words": variants[0]["words"], "sentences": [cue("你好！", .1, .8)]}
        whole = {"text": base_data["text"], "words": variants[-1]["words"] + base_words[2:]}
        data = tts.subtitle_data([first, {"text": "再见！", "words": base_words[2:]}, whole, whole],
                                 whole["text"], 2)
        assert data == {"text": whole["text"], "words": whole["words"],
                        "sentences": [cue("你好。", .11, .86), cue("再见！", 1.1, 1.8)]}
        partial = {"text": "好。再", "words": [variants[0]["words"][1], base_words[2]]}
        assert tts.clip_subtitles(base_plan["clips"][0], tts.request_body(base_plan["clips"][0]),
                                  [variants[0], partial], 2)[1] == "invalid_subtitles", "真正的部分重叠不能猜合并"
        fresh_invalid(base_plan, [variants[0], partial], directory / "ambiguous")

    def punctuation_ownership(directory):
        shared = [word("你", .1, .4), word("好", .4, .8), word("。", .8, .8),
                  word("再", .8, 1.4), word("见！", 1.4, 1.8)]
        expected = [cue("你好。", .1, .8), cue("再见！", .8, 1.8)]
        data = tts.subtitle_data([{"text": base_data["text"], "words": shared}], base_data["text"], 2)
        assert data == {"text": base_data["text"], "words": shared, "sentences": expected}
        assert tts.sentence_cues(base_data["text"], shared) == expected
        public_data(data)
        repeated = [word("你", .1, .4), word("好", .4, .8), word("。", .8, .81),
                    word("。", .81, .82), word("再", .82, 1.4), word("见", 1.4, 1.8),
                    word("！", 1.8, 1.81), word("！", 1.81, 1.82)]
        text = "你好。。再见！！"
        data = tts.subtitle_data([{"text": text, "words": repeated}], text, 2)
        assert data["words"] == repeated
        assert data["sentences"] == [cue("你好。。", .1, .82), cue("再见！！", .82, 1.82)]
        numeric_words = [word("编号", .1, .3), word("一百二十三", .3, 1),
                         word("你", 1.2, 1.4), word("好。", 1.4, 1.6)]
        assert tts.sentence_cues("编号123。你好。", numeric_words) == [
            cue("编号123。", .1, 1), cue("你好。", 1.2, 1.6)], "后句的唯一词锚点应保留数字规范化句界"
        out = directory / "shared-cache"
        cached(out, data={"text": base_data["text"], "words": shared, "sentences": expected})
        tts.render(base_plan, out)
        assert json.loads((out / "timeline.json").read_text())["words"] == [
            {**item, "clip": base_plan["clips"][0]["id"]} for item in shared]

    def spanning_tokens(directory):
        single = [word("甲。乙。", 0, 1)]
        assert tts.sentence_cues("甲。乙。", single) == [cue("甲。乙。", 0, 1)]
        plan = reviewed_plan("甲。乙。")
        data, reason = tts.clip_subtitles(plan["clips"][0], tts.request_body(plan["clips"][0]),
                                        [{"text": "甲。乙。", "words": single}], 2)
        assert reason == "" and data["sentences"] == [cue("甲。乙。", 0, 1)]
        words = [word("前。", 0, .2), word("甲。乙。", .3, 1), word("后。", 1.2, 1.5)]
        text = "前。甲。乙。后。"
        expected = [cue("前。", 0, .2), cue("甲。乙。", .3, 1), cue("后。", 1.2, 1.5)]
        assert tts.sentence_cues(text, words) == expected, "跨句词只能拥有一个合并后的 cue"
        data = tts.subtitle_data([{"text": text, "words": words}], text, 2)
        assert data == {"text": text, "words": words, "sentences": expected}
        public_data(data)

    def empty_timestamp_metadata(directory):
        empty = {"text": base_data["text"], "words": [], "sentences": []}
        out = directory / "affirmative-empty"
        manifest = cached(out, data=empty)
        entry = manifest[fingerprint(base_plan["clips"][0])]
        entry.update(timestamps=True, timestamps_reason="")
        tts.save(out / "manifest.json", manifest)
        cache_rejected(base_plan, out)
        for name, metadata in (("explicit-not-returned", True), ("legacy-empty", False)):
            out = directory / name
            cached(out, data=empty, metadata=metadata)
            for _ in range(2):
                result = tts.render(base_plan, out)
                assert result["timestamps"] is False
            entry = json.loads((out / "manifest.json").read_text())[fingerprint(base_plan["clips"][0])]
            assert entry["timestamps"] is False and entry["timestamps_reason"] == "not_returned"

    def cache_cue_ownership(directory):
        shifted_text = copy.deepcopy(base_data)
        shifted_text["sentences"] = [cue("你好。再", .1, .8), cue("见！", 1.1, 1.8)]
        assert "".join(item["text"] for item in shifted_text["sentences"]) == shifted_text["text"]
        out = directory / "shifted-text-boundary"
        cached(out, data=shifted_text)
        cache_rejected(base_plan, out)
        numeric_plan = reviewed_plan("编号123。你好。")
        numeric = {"text": "编号123。你好。", "words": [word("编号", .1, .3), word("一百二十三", .3, 1),
                   word("你", 1.2, 1.4), word("好。", 1.4, 1.6)],
                   "sentences": [cue("编号123。", .1, 1), cue("你好。", 1.2, 1.6)]}
        out = directory / "normalized-number"
        cached(out, plan=numeric_plan, data=numeric)
        assert tts.render(numeric_plan, out)["timestamps"] is True
        timeline = json.loads((out / "timeline.json").read_text())
        assert timeline["sentences"] == [{**item, "clip": numeric_plan["clips"][0]["id"]}
                                         for item in numeric["sentences"]]
        revised = copy.deepcopy(base_data)
        revised.update(text="你好！\n再见。", sentences=[cue("你好！", .1, .8), cue("再见。", 1.1, 1.8)])
        out = directory / "punctuation-whitespace-revision"
        cached(out, data=revised)
        assert tts.render(base_plan, out)["timestamps"] is True
        timeline = json.loads((out / "timeline.json").read_text())
        assert timeline["clips"][0]["subtitle_text"] == revised["text"]
        assert [item["text"] for item in timeline["sentences"]] == ["你好！", "再见。"]

    def zero_duration_speech(directory):
        plan = reviewed_plan("你好。")
        event = {"text": "你好。", "words": [word("你好。", .5, .5)]}
        fresh_invalid(plan, [event], directory / "fresh-zero")
        out = directory / "cached-zero"
        cached(out, plan=plan, data={**event, "sentences": [cue("你好。", .5, .5)]})
        cache_rejected(plan, out)
        positive = [word("你好", .1, .5), word("。", .5, .5)]
        assert tts.subtitle_data([{"text": "你好。", "words": positive}], "你好。", 2) == {
            "text": "你好。", "words": positive, "sentences": [cue("你好。", .1, .5)]}

    def bounded_wav_reads(directory):
        assert tts.PCM_CHUNK_FRAMES == 24000
        plan = copy.deepcopy(base_plan)
        plan["clips"] = []
        lengths = [24001, 72007, 96011]
        empty = {"text": base_data["text"], "words": [], "sentences": []}
        manifest, sources = {}, {}
        for index, frames in enumerate(lengths):
            clip = copy.deepcopy(base_plan["clips"][0])
            clip.update(id="long-" + str(index), direction="自然清楚地说。" + "再" * index,
                        pause_after_ms=30000 if index == 2 else index + 1)
            plan["clips"].append(clip)
            fp = fingerprint(clip)
            audio = bytes((index + 1, 0)) * frames
            sources[fp] = (frames, audio)
            directory.mkdir(parents=True, exist_ok=True)
            (directory / (fp + ".wav")).write_bytes(tts.wav_bytes(audio))
            tts.save(directory / (fp + ".words.json"), empty)
            manifest[fp] = {"status": "complete", "words_file": fp + ".words.json",
                            "timestamps": False, "timestamps_reason": "not_returned"}
        duplicate = copy.deepcopy(plan["clips"][0])
        duplicate.update(id="long-duplicate", pause_after_ms=3)
        plan["clips"].insert(1, duplicate)
        tts.save(directory / "manifest.json", manifest)
        sizes, writes, descriptors = [], [], []
        original_read = wave.Wave_read.readframes
        original_write = wave.Wave_write.writeframesraw
        original_concatenate = tts.concatenate_wavs

        def read(wav, frames):
            sizes.append(frames)
            assert 0 <= frames <= tts.PCM_CHUNK_FRAMES, "WAV 读取不能按整段/整文件请求"
            return original_read(wav, frames)

        def write(wav, data):
            writes.append(len(data))
            assert len(data) <= 2 * tts.PCM_CHUNK_FRAMES, "最终 PCM（包括长停顿）必须分块写入"
            return original_write(wav, data)

        def no_pcm(value):
            assert not isinstance(value, (bytes, bytearray, memoryview)), "缓存/拼接描述符不能保留 PCM"
            if isinstance(value, dict):
                for item in value.values():
                    no_pcm(item)
            elif isinstance(value, (tuple, list)):
                for item in value:
                    no_pcm(item)

        def concatenate(segments, final_path):
            no_pcm(segments)
            assert all(type(segment["frames"]) is int for segment in segments)
            descriptors.extend(copy.deepcopy(segments))
            return original_concatenate(segments, final_path)

        with patch.object(wave.Wave_read, "readframes", read), patch.object(
                wave.Wave_write, "writeframesraw", write), patch.object(
                tts, "concatenate_wavs", side_effect=concatenate), patch.object(
                tts, "read_cached_clip", wraps=tts.read_cached_clip) as inspections:
            tts.render(plan, directory)
            assert inspections.call_count == len(sources), "同 fingerprint 只预检一次，不重复读取"
            clip = plan["clips"][0]
            result = tts.read_cached_clip(clip, tts.request_body(clip), directory,
                                          fingerprint(clip), manifest[fingerprint(clip)])
            assert type(result[0]) is int and result[0] == lengths[0], "read_cached_clip 返回帧数，不是 PCM"
            no_pcm(result)
        assert sizes and writes and descriptors
        total = sum(sources[fingerprint(clip)][0] + 24 * clip["pause_after_ms"] for clip in plan["clips"])
        timeline = json.loads((directory / "timeline.json").read_text())
        assert timeline["duration"] == total / 24000
        assert timeline["clips"][1]["offset"] == (24001 + 24) / 24000
        assert [segment["frames"] for segment in descriptors] == [24001, 24001, 72007, 96011]
        expected = b"".join(sources[fingerprint(clip)][1] + b"\0\0" * (24 * clip["pause_after_ms"])
                            for clip in plan["clips"])
        with wave.open(str(directory / "final.wav"), "rb") as wav:
            assert wav.getnframes() == total
            actual = bytearray()
            while part := wav.readframes(tts.PCM_CHUNK_FRAMES):
                actual.extend(part)
        assert actual == expected, "非整秒帧数、重复缓存、拼接顺序与末尾停顿必须逐样本正确"
        later = directory / (fingerprint(plan["clips"][-1]) + ".wav")
        later.write_bytes(later.read_bytes()[:-2])
        cache_rejected(plan, directory)

    def manifest_write_lifecycle(directory):
        original_save = tts.save
        writes = []

        def save(path, data):
            path = Path(path)
            if path.name == "manifest.json":
                snapshot = copy.deepcopy(data)
                for fp, entry in snapshot.items():
                    if entry["status"] == "complete":
                        assert (path.parent / (fp + ".wav")).is_file()
                        assert isinstance(json.loads((path.parent / (fp + ".words.json")).read_text()), dict)
                writes.append(snapshot)
            original_save(path, data)
            if path.name == "manifest.json":
                assert json.loads(path.read_text()) == data, "状态写入必须在调用继续前落盘"

        out = directory / "warm"
        cached(out)
        with patch.object(tts, "save", side_effect=save):
            tts.render(base_plan, out)
            assert writes == [], "正常 warm hit 不得重写 manifest"
            paused = copy.deepcopy(base_plan)
            paused["clips"][0]["pause_after_ms"] = 30000
            tts.render(paused, out)
            assert writes == [], "只改停顿不能重写请求状态"
        legacy_plan = copy.deepcopy(base_plan)
        second = copy.deepcopy(base_plan["clips"][0])
        second.update(id="second-legacy", direction="轻声清楚地说。")
        legacy_plan["clips"].append(second)
        empty = {"text": base_data["text"], "words": [], "sentences": []}
        out = directory / "legacy-batch"
        cached(out, plan=legacy_plan, data=empty, metadata=False)
        with patch.object(tts, "save", side_effect=save):
            tts.render(legacy_plan, out)
            assert len(writes) == 1 and len(writes[0]) == 2, "多个旧元数据迁移必须批量一次保存"
            assert all(entry["timestamps_reason"] == "not_returned" and entry["timestamps"] is False
                       for entry in writes[0].values())
            writes.clear()
            tts.render(legacy_plan, out)
            assert writes == [], "已迁移旧缓存的 warm hit 不再写 manifest"
        duplicate_plan = copy.deepcopy(base_plan)
        for index in range(2):
            duplicate = copy.deepcopy(base_plan["clips"][0])
            duplicate.update(id="new-duplicate-" + str(index), pause_after_ms=index + 1)
            duplicate_plan["clips"].append(duplicate)
        out = directory / "new-request"
        fp = fingerprint(base_plan["clips"][0])

        def opener():
            entry = json.loads((out / "manifest.json").read_text())[fp]
            assert entry["status"] == "uncertain", "打开网络连接前必须已有持久 uncertain 记录"
            assert not (out / (fp + ".wav")).exists() and not (out / (fp + ".words.json")).exists()
            class Opener:
                def open(self, request, timeout):
                    assert request.get_header("X-api-key") == fake_key
                    assert json.loads(request.data) == tts.request_body(base_plan["clips"][0])
                    return Response(stream([base_data]))
            return Opener()

        with patch.object(tts, "save", side_effect=save), patch.object(
                tts.urllib.request, "build_opener", side_effect=lambda *args: opener()) as network:
            tts.render(duplicate_plan, out)
            assert network.call_count == 1, "新请求的重复 fingerprint 不能再次合成"
            assert len(writes) == 2, "重复片段不能在 uncertain/complete 两次持久写之外重写 manifest"
            assert [snapshot[fp]["status"] for snapshot in writes] == ["uncertain", "complete"]
            writes.clear()
            tts.render(duplicate_plan, out)
            assert not writes and network.call_count == 1
        out = directory / "failed-request"

        def broken_opener(*args):
            assert json.loads((out / "manifest.json").read_text())[fp]["status"] == "uncertain"
            raise OSError("offline synthetic connection failure")

        with patch.object(tts, "save", side_effect=save), patch.object(
                tts.urllib.request, "build_opener", side_effect=broken_opener) as network:
            fails(lambda: tts.render(base_plan, out), "失败请求必须停止")
            assert len(writes) == 2 and all(snapshot[fp]["status"] == "uncertain" for snapshot in writes)
            entry = json.loads((out / "manifest.json").read_text())[fp]
            assert entry["status"] == "uncertain" and entry["error_type"] == "OSError"
            assert not (out / (fp + ".wav")).exists() and not (out / (fp + ".words.json")).exists()
            writes.clear()
            fails(lambda: tts.render(base_plan, out), "uncertain 请求不能自动重发")
            assert not writes and network.call_count == 1

    def cache_without_regeneration(directory):
        out = directory / "normal"
        cached(out)
        with patch.object(tts, "subtitle_data", side_effect=AssertionError("缓存命中不得重建字幕事件")), patch.object(
                tts, "sentence_cues", side_effect=AssertionError("已有保存 cues 不得废弃后重建")):
            tts.render(base_plan, out)
            normalized = copy.deepcopy(base_data)
            normalized["words"] = list(reversed(base_words)) + [base_words[0]]
            tts.save(out / (fingerprint(base_plan["clips"][0]) + ".words.json"), normalized)
            tts.render(base_plan, out)
            timeline = json.loads((out / "timeline.json").read_text())
            assert timeline["words"] == [{**item, "clip": base_plan["clips"][0]["id"]} for item in base_words]
        old = copy.deepcopy(base_data)
        del old["sentences"]
        out = directory / "old-no-sentences"
        cached(out, data=old)
        with patch.object(tts, "subtitle_data", side_effect=AssertionError("旧缓存也只做直接规范化")), patch.object(
                tts, "sentence_cues", wraps=tts.sentence_cues) as reconstruction:
            tts.render(base_plan, out)
            assert reconstruction.call_count == 1, "缺 sentences 的旧 sidecar 只重建一次"
            tts.render(base_plan, out)
            assert reconstruction.call_count == 1, "重建结果须保存，随后 warm hit 不再重建"
        saved = json.loads((out / (fingerprint(base_plan["clips"][0]) + ".words.json")).read_text())
        assert saved == base_data

    checks = [("1 huge JSON numbers", huge_json_numbers),
              ("2 cumulative revisions", cumulative_revisions),
              ("3 punctuation ownership", punctuation_ownership),
              ("4 spanning tokens", spanning_tokens),
              ("5 empty timestamp metadata", empty_timestamp_metadata),
              ("6 cache cue ownership", cache_cue_ownership),
              ("7 zero duration speech", zero_duration_speech),
              ("8 bounded WAV reads", bounded_wav_reads),
              ("9 manifest lifecycle", manifest_write_lifecycle),
              ("10 cache without regeneration", cache_without_regeneration)]
    failures = []
    with tempfile.TemporaryDirectory(prefix="volce-timestamp-review-") as directory, patch.dict(
            os.environ, {"VOLC_TTS_API_KEY": fake_key}, clear=True), patch.object(
            tts.urllib.request, "build_opener", side_effect=AssertionError("离线回归不得发出真实请求")):
        for index, (name, check) in enumerate(checks):
            try:
                check(Path(directory) / str(index + 1))
            except Exception as exc:
                failures.append(f"{name}: {type(exc).__name__}: {exc}")
        assert all(fake_key not in path.read_text() for path in Path(directory).rglob("*.json"))
    if failures:
        raise AssertionError("timestamp_review_checks 回归失败：\n" + "\n".join(failures))


def mixed_checks():
    text = "Anthropic 发布 Claude Haiku 5.5，输入每百万 token 零点一美元，比 DeepSeek V4.1-Flash 还便宜。"
    voice = "zh_male_youyoujunzi_uranus_bigtts"
    table = tts.load_pronunciations(tts.PRONUNCIATIONS)
    draft = tts.prepare(text, voice)
    clip = draft["clips"][0]
    assert clip["text"] == text and clip["voice"] == voice
    assert tts.resolve_resource(clip) == "seed-tts-2.0"
    assert all(text[r["start"]:r["start"] + len(r["text"])] == r["text"] for r in clip["readings"])
    fails(lambda: tts.validate(draft, True), "混读不能绕过中文校对")
    for row in clip["readings"]:
        row["status"] = "reviewed"
    clip["reference_text"] = "上文讨论 OpenAI API，不朗读引用。"
    tts.validate(draft, True)
    body = tts.request_body(clip, pronunciation_table=table)
    additions = json.loads(body["req_params"]["additions"])
    assert body["req_params"]["text"] == text
    assert body["req_params"]["audio_params"]["enable_subtitle"] is True
    assert additions["explicit_language"] == "zh-cn"
    assert table["decimal_point"] == "点", "面向中文用户默认中文型号读法"
    assert additions["pronunciation_dict"]["tone"] == ["5.5/5点5", "V4.1/V 4点1"]
    context = additions["context_texts"]
    assert len(context) == 1 and all(hint in context[0] for hint in ("an-THROP-ik", "klawd", "HIGH-koo"))
    assert "API/A P I" not in body["req_params"]["additions"], "引用中的缩写不控制正文"
    assert "ssml" not in body["req_params"] and "phoneme" not in additions
    assert all(word not in additions["pronunciation_dict"]["tone"] for word in ("DeepSeek", "token"))
    dot = copy.deepcopy(table)
    dot["decimal_point"] = "point"
    dot_body = tts.request_body(clip, pronunciation_table=dot)
    assert json.loads(dot_body["req_params"]["additions"])["pronunciation_dict"]["tone"] == ["5.5/five point five", "V4.1/V four point one"]
    assert dot_body["req_params"]["text"] == text
    inactive = copy.deepcopy(table)
    inactive["words"]["Unused"] = "unused"
    inactive["acronyms"]["CPU"] = "C P U"
    inactive["models"].append("V2.0")
    inactive["words"] = dict(reversed(list(inactive["words"].items())))
    assert tts.request_body(clip, pronunciation_table=inactive) == body
    assert tts.request_fingerprint(body, "seed-tts-2.0") != tts.request_fingerprint(dot_body, "seed-tts-2.0")
    legacy = copy.deepcopy(draft)
    del legacy["pronunciation_table"]
    assert "pronunciation_dict" not in json.loads(tts.request_body(legacy["clips"][0])["req_params"]["additions"])
    aliases = "KV API MLA GPU IPO S-1 KV cache OpenAI OpenRouter token"
    acronym = {"text": aliases, "voice": voice, "readings": []}
    acronym_body = tts.request_body(acronym, pronunciation_table=table)
    assert acronym_body["req_params"]["text"] == aliases
    assert json.loads(acronym_body["req_params"]["additions"])["pronunciation_dict"]["tone"] == [
        key + "/" + value for key, value in sorted(table["acronyms"].items())]
    assert tts.prepare("Claude 5.5")["clips"][0]["explicit_language"] == "en"
    assert tts.prepare("5.5")["clips"][0]["text"] == "5.5"
    assert "pronunciation_table" not in tts.prepare("价格5.5美元。"), "纯中文价格不自动改为英语"
    assert "pronunciation_table" in tts.prepare("价格5.5美元。", pronunciation_table=table)
    for invalid in ("", "   ", "日本語カナ", "中文 Русский", "中文 Ελληνικά"):
        fails(lambda: tts.prepare(invalid), "不宣称支持未知语种或空稿")
    for phrase in ("API OpenAPI", "KV KValue", "S-1 S-10", "5.5 15.5"):
        bad = {"text": phrase, "voice": voice, "readings": []}
        fails(lambda: tts.request_body(bad, pronunciation_table=table), "全局词典不能误改子串")
    embedded = {"text": "OpenAPI KValue S-10 15.5", "voice": voice, "readings": []}
    assert "pronunciation_dict" not in json.loads(tts.request_body(embedded, pronunciation_table=table)["req_params"]["additions"])
    extended = copy.deepcopy(table)
    extended["decimal_point"] = "point"
    extended["models"].append("15.5")
    assert tts.table_controls({"text": "5.5 15.5"}, extended)[0]["15.5"] == "fifteen point five"
    tts.readings({"text": "5.5 15.5"}, pronunciation_table=extended)
    assert tts.table_controls({"text": "中文API接口"}, table)[0] == {"API": "A P I"}
    conflict = {"text": "API", "voice": voice, "pronunciation_dict": {"tone": ["API/another word"]}}
    fails(lambda: tts.request_body(conflict, pronunciation_table=table), "发音表与手工词典不静默覆盖")
    conflict["pronunciation_dict"]["tone"] = ["API/A P I"]
    assert len(json.loads(tts.request_body(conflict, pronunciation_table=table)["req_params"]["additions"])["pronunciation_dict"]["tone"]) == 1
    raw = {"text": "omg", "voice": voice, "pronunciation_dict": {"tone": ["omg/oh my god"]}}
    assert tts.request_body(raw)["req_params"]["text"] == "omg"
    for entries in (["OpenRouter/router"], ["KV cache/cache"], ["API/A/P/I"], ["API/"], ["API/(bogus1)"]):
        raw["pronunciation_dict"]["tone"] = entries
        fails(lambda: tts.request_body(raw), "遵守官方字典长度与语法")
    for field, value in (("version", True), ("words", []), ("words", {"Claude": "克劳德"}),
                         ("acronyms", {"LONGACRONYM": "L"}), ("models", ["V4.1", "V4.1"]),
                         ("models", ["V123456.78"]), ("models", ["V4"]), ("decimal_point", "dot")):
        bad = copy.deepcopy(table)
        bad[field] = value
        fails(lambda: tts.validate_pronunciations(bad), "发音表类型与范围校验")
    bad = copy.deepcopy(table)
    bad["extra"] = True
    fails(lambda: tts.validate_pronunciations(bad), "拒绝未知表字段")
    bad = copy.deepcopy(table)
    bad["words"]["API"] = None
    fails(lambda: tts.validate_pronunciations(bad), "同词不同通道冲突")
    bad_plan = copy.deepcopy(draft)
    bad_plan["clips"][0]["explicit_language"] = "en"
    fails(lambda: tts.validate(bad_plan), "混读不能强制纯英语")
    for language in ("zh", "cn", [], True):
        bad_plan["clips"][0]["explicit_language"] = language
        fails(lambda: tts.validate(bad_plan), "只接受官方语言枚举")
    assert tts.sentence_ends("Claude 5.5. DeepSeek V4.1-Flash! API?") == [11, 32, 37]
    assert tts.sentence_ends("Dr. Smith uses V4.1. Next.") == [20, 26]
    assert tts.sentence_ends("OpenAI e.g. API. Claude.") == [16, 24]
    assert tts.english_integer("20") == "twenty"
    assert tts.english_integer("1234") == "one thousand two hundred thirty four"
    assert tts.english_integer("0004") == "zero zero zero four"
    hint_changed = copy.deepcopy(table)
    hint_changed["words"]["Claude"] = "KLAWD"
    assert tts.request_body(clip, pronunciation_table=hint_changed) != body
    unrestricted = copy.deepcopy(table)
    unrestricted["words"]["OpenRouter"] = "open router"
    assert "open router" in tts.request_body({"text": "OpenRouter", "voice": voice},
                                           pronunciation_table=unrestricted)["req_params"]["additions"]
    safe_han = {"text": "银行 API", "voice": voice, "readings": [
        {"start": 0, "text": "银行", "pinyin": ["yin2", "hang2"], "status": "reviewed", "delivery": "native"}],
        "pronunciation_dict": {"tone": ["银行/AB"]}}
    fails(lambda: tts.request_body(safe_han, pronunciation_table=table), "英文转写不能伪装成汉字读音")
    long = ("Claude Haiku 5.5. " * 60)
    assert "".join(c["text"] for c in tts.prepare(long)["clips"]) == long
    subtitle_text = "Anthropic 发布 Claude Haiku 5.5。DeepSeek V4.1-Flash!"
    labels = ["Anthropic", "发", "布", "Claude", "Haiku", "5.5。", "DeepSeek", "V4.1-Flash!"]
    words = [{"word": label, "startTime": i / 2, "endTime": (i + 1) / 2, "confidence": 0.9}
             for i, label in enumerate(labels)]
    data = tts.subtitle_data([{"text": subtitle_text, "words": words}], subtitle_text, 4)
    assert data["words"] == words and len(data["sentences"]) == 2
    assert [cue["endTime"] for cue in data["sentences"]] == [3.0, 4.0]
    supplier_text = "API 调用。"
    supplier_words = [{"word": "A P I", "startTime": 0, "endTime": 1, "confidence": 0.9},
                      {"word": "调用。", "startTime": 1, "endTime": 2, "confidence": 0.9}]
    assert tts.subtitle_data([{"text": supplier_text, "words": supplier_words}], supplier_text, 2)["words"] == supplier_words
    with tempfile.TemporaryDirectory(prefix="volce-mixed-check-") as directory:
        out = Path(directory)
        tts.preview(draft, out / "preview")
        shown = (out / "preview/director.md").read_text()
        assert all(value in shown for value in ("Anthropic", "an-THROP-ik", "英语原生读法", "服务端文本转写", "zh-cn"))
        with patch.dict(os.environ, {}, clear=True), patch.object(
                tts.urllib.request, "build_opener", side_effect=AssertionError("dry-run 不能联网")):
            assert tts.render(draft, out / "dry", dry_run=True)["clips"] == 1
        assert json.loads((out / "dry/requests.json").read_text()) == [body]
        duplicate = out / "duplicate.json"
        duplicate.write_text('{"version":1,"version":1}')
        fails(lambda: tts.load_pronunciations(duplicate), "JSON 重复字段不可悄悄丢弃")
        profile = out / "pronunciations.json"
        tts.save(profile, table)
        snapshot = tts.prepare(text, voice, pronunciation_table=tts.load_pronunciations(profile))
        tts.save(profile, dot)
        assert snapshot["pronunciation_table"]["decimal_point"] == "点"
        pcm = b"\x00\x00" * (24000 * 4)
        frames = [json.dumps({"code": 0, "data": base64.b64encode(pcm).decode()}),
                  json.dumps({"code": 20000000}), json.dumps({"code": 0, "sentence": {"text": subtitle_text, "words": words}})]
        class Response(io.BytesIO):
            headers = {"X-Tt-Logid": "offline-mixed"}
        class Opener:
            def open(self, request, timeout):
                assert json.loads(request.data) == body
                return Response("\n".join(frames).encode())
        with patch.dict(os.environ, {"VOLC_TTS_API_KEY": "offline-fake-key"}, clear=True), patch.object(
                tts.urllib.request, "build_opener", return_value=Opener()) as network:
            summary = tts.render(draft, out / "audio")
            assert summary["timestamps"] is True and network.call_count == 1
            draft["clips"][0]["pause_after_ms"] = 250
            tts.render(draft, out / "audio")
            assert network.call_count == 1
        sidecar = next((out / "audio").glob("*.words.json"))
        assert json.loads(sidecar.read_text())["words"] == words
        timeline = json.loads((out / "audio/timeline.json").read_text())
        assert timeline["duration"] == 4.25 and timeline["clips"][0]["text"] == text
        assert all({k: w[k] for k in words[i]} == words[i] for i, w in enumerate(timeline["words"]))
        assert "DeepSeek" in (out / "audio/final.srt").read_text()
        segments = [{"clip": {**clip, "id": ident}, "frames": 24000 * 4, "audio": "clip.wav",
                     "words_file": "clip.words.json", "subtitles": data, "timestamps_reason": ""}
                    for ident in ("001", "002")]
        shifted = tts.build_timeline(segments)
        assert shifted["clips"][1]["offset"] == 4.25 and shifted["duration"] == 8.5
        for original, shifted_word in zip(words, shifted["words"][len(words):]):
            assert shifted_word["word"] == original["word"] and shifted_word["confidence"] == original["confidence"]
            assert shifted_word["startTime"] == original["startTime"] + 4.25
            assert shifted_word["endTime"] == original["endTime"] + 4.25
        assert all("offline-fake-key" not in f.read_text() for f in (out / "audio").glob("*.json"))


def demo():
    plan = json.loads((ROOT / "examples/chinese/plan.json").read_text(encoding="utf-8"))
    text = "".join(c["text"] for c in plan["clips"])
    draft = tts.prepare(text)
    assert "".join(c["text"] for c in draft["clips"]) == text
    assert any(r["text"] == "行" for r in draft["clips"][0]["readings"])
    fails(lambda: tts.validate(draft, complete=True), "候选不能冒充已校对")
    tts.validate(plan, complete=True)
    body = tts.request_body(plan["clips"][0])
    assert body["req_params"]["text"] == plan["clips"][0]["text"]
    assert "〔" not in body["req_params"]["text"]
    tones = json.loads(body["req_params"]["additions"])["pronunciation_dict"]["tone"]
    assert "银行/(yin2)(hang2)" in tones and "行长/(hang2)(zhang3)" in tones
    assert "还款/(huan2)(kuan3)" in json.loads(tts.request_body(plan["clips"][2])[
        "req_params"]["additions"])["pronunciation_dict"]["tone"]
    hua = tts.prepare("华老栓忽然坐起身。")
    for row in hua["clips"][0]["readings"]:
        row["status"] = "reviewed"
        if row["text"] == "华":
            row.update(pinyin=["hua4"], delivery="spoken_alias", spoken_alias="桦", alias_approved=True)
    hua_body = tts.request_body(hua["clips"][0])["req_params"]
    assert hua_body["text"] == "桦老栓忽然坐起身。"
    assert hua["clips"][0]["text"] == "华老栓忽然坐起身。"
    additions = json.loads(hua_body["additions"])
    assert len(additions["context_texts"]) == 1 and "hua4" in additions["context_texts"][0]
    assert "ssml" not in hua_body and "pronunciation_dict" not in additions
    expressive = copy.deepcopy(hua)
    clip = expressive["clips"][0]
    clip.update(direction="用低沉、克制的语气，稍慢地说。", reference_text="屋内寂静，只有窗外的风声。",
                speech_rate=-10, explicit_dialect="beijing")
    tts.validate(expressive, True)
    expressive_body = tts.request_body(clip)["req_params"]
    expressive_additions = json.loads(expressive_body["additions"])
    combined = expressive_additions["context_texts"]
    assert len(combined) == 1
    assert all(value in combined[0] for value in (clip["direction"], clip["reference_text"], "hua4", "不朗读"))
    assert expressive_body["text"] == hua_body["text"] and "风声" not in expressive_body["text"]
    assert expressive_body["audio_params"]["speech_rate"] == -10
    assert expressive_additions["explicit_dialect"] == "beijing"
    for name, value in (("reference_text", []), ("reference_text", "中" * 501),
                        ("reference_text", "Русский 上文"), ("explicit_dialect", "unknown"),
                        ("explicit_dialect", []), ("section_id", 12)):
        bad_control = copy.deepcopy(expressive)
        bad_control["clips"][0][name] = value
        fails(lambda: tts.validate(bad_control), "拒绝无效指令控制字段")
    native_dict = copy.deepcopy(hua)
    native_clip = native_dict["clips"][0]
    native_clip.update(section_id="story-opening", pronunciation_dict={"tone": ["华/桦"]})
    native_row = native_clip["readings"][0]
    native_row.update(delivery="native")
    del native_row["spoken_alias"]
    del native_row["alias_approved"]
    tts.validate(native_dict, True)
    dict_request = tts.request_body(native_clip)["req_params"]
    dict_additions = json.loads(dict_request["additions"])
    assert dict_request["text"] == "华老栓忽然坐起身。", "原生字典转写在服务端进行"
    assert dict_additions["pronunciation_dict"]["tone"] == ["华/桦"]
    assert dict_additions["section_id"] == "story-opening"
    native_clip["pronunciation_dict"]["tone"] = ["华/(hua4)"]
    tts.validate(native_dict, True)
    assert json.loads(tts.request_body(native_clip)["req_params"]["additions"])["pronunciation_dict"]["tone"] == ["华/(hua4)"]
    for entries in (["华/花"], ["华/桦老"], ["华/(abc1)"], ["华/桦", "华/桦"], ["华/oh my god"], ["华"]):
        native_clip["pronunciation_dict"]["tone"] = entries
        fails(lambda: tts.validate(native_dict, True), "字典不可覆盖位置读音或包含无效规则")
    transcription = tts.prepare("编号123。")
    for row in transcription["clips"][0]["readings"]:
        row["status"] = "reviewed"
    transcription["clips"][0]["pronunciation_dict"] = {"tone": ["123/一百二十三"]}
    tts.validate(transcription, True)
    assert "123/一百二十三" in tts.request_body(transcription["clips"][0])["req_params"]["additions"]
    unapproved = copy.deepcopy(hua)
    unapproved["clips"][0]["readings"][0]["alias_approved"] = False
    fails(lambda: tts.validate(unapproved, True), "别名不能隐式替换")
    wrong_alias = copy.deepcopy(hua)
    wrong_alias["clips"][0]["readings"][0]["spoken_alias"] = "花"
    fails(lambda: tts.validate(wrong_alias, True), "别名必须匹配目标声调")
    mixed = {"text": "行行", "readings": [
        {"start": 0, "text": "行", "pinyin": ["hang2"], "status": "reviewed", "delivery": "dictionary"},
        {"start": 1, "text": "行", "pinyin": ["xing2"], "status": "reviewed", "delivery": "native"}]}
    fails(lambda: tts.readings(mixed, True), "字典不能覆盖另一位置的自然读法")
    mixed["readings"][0]["delivery"] = "instruction"
    mixed["readings"][1]["delivery"] = "instruction"
    fails(lambda: tts.readings(mixed, True), "同词相反指令必须消歧")
    twice = tts.prepare("华老栓忽然坐起身。华老栓又坐下。")
    for row in twice["clips"][0]["readings"]:
        row['status'] = 'reviewed'
        if row['text'] == '华' and row['start'] == 0:
            row.update(pinyin=['hua4'],delivery='spoken_alias',spoken_alias='桦',alias_approved=True)
    assert tts.request_body(twice['clips'][0])['req_params']['text'] == "桦老栓忽然坐起身。华老栓又坐下。"
    bad = copy.deepcopy(plan)
    bad["clips"][0]["readings"][0]["pinyin"][0] = "abc1"
    fails(lambda: tts.validate(bad), "拼音必须为实际音节")
    bad = copy.deepcopy(plan)
    bad["clips"][0]["text"] = "变动" + bad["clips"][0]["text"]
    fails(lambda: tts.validate(bad, complete=True), "编辑原文后旧位置不可接受")
    bad = copy.deepcopy(plan)
    bad["clips"][0]["readings"].append({"start": 1, "text": "行", "pinyin": ["xing2"], "status": "reviewed"})
    fails(lambda: tts.validate(bad), "标注不能重叠")
    conflict = {"text": "行行", "readings": [
        {"start": 0, "text": "行", "pinyin": ["hang2"], "status": "reviewed"},
        {"start": 1, "text": "行", "pinyin": ["xing2"], "status": "reviewed"}]}
    fails(lambda: tts.readings(conflict, True), "同词多读音不可覆盖")
    # 从位置 0 的长词跨过了单字标注，必须拒绝。
    shadow = {"text": "重重重", "readings": [
        {"start": 0, "text": "重", "pinyin": ["zhong4"], "status": "reviewed"},
        {"start": 1, "text": "重重", "pinyin": ["chong2", "chong2"], "status": "reviewed"}]}
    fails(lambda: tts.readings(shadow, True), "最长匹配必须符合位置标注")
    assert tts.prepare("Hello 中文")["clips"][0]["text"] == "Hello 中文"
    fails(lambda: tts.prepare("中" * 501), "不截断长句")
    pcm = b"\x01\x00" * 240
    frames = [json.dumps({"code": 0, "data": base64.b64encode(pcm).decode()}).encode(),
              b'{"code":20000000,"usage":{"text_words":9}}']
    assert tts.decode_stream(frames) == (pcm, {"text_words": 9}, [])
    fails(lambda: tts.decode_stream(frames[:1]), "断流不能当成功")
    fails(lambda: tts.decode_stream([b'{"code":55000000}']), "错误码不能忽略")
    class Response(io.BytesIO):
        headers = {"X-Tt-Logid": "offline-check"}
    class Opener:
        def open(self, request, timeout):
            assert request.full_url == tts.ENDPOINT
            assert request.get_header("X-api-key") == "offline-fake-key"
            assert request.get_header("X-api-resource-id") == "seed-tts-2.0"
            assert json.loads(request.data)["req_params"]["text"] in text
            return Response(b"\n".join(frames))
    with tempfile.TemporaryDirectory(prefix="volce-check-") as directory:
        out = Path(directory)
        tts.preview(draft, out / "draft")
        assert "待校对" in (out / "draft/director.html").read_text()
        tts.preview(plan, out / "reviewed")
        assert "háng" in (out / "reviewed/director.html").read_text()
        tts.preview(hua, out / "hua")
        assert "<ruby" in (out / "hua/director.html").read_text()
        assert "可听替换：桦" in (out / "hua/director.html").read_text()
        tts.preview(expressive, out / "expressive")
        for filename in ("director.html", "director.md"):
            displayed = (out / "expressive" / filename).read_text()
            assert all(value in displayed for value in (clip["direction"], clip["reference_text"], "北京话", "-10"))
        with patch.dict(os.environ, {}, clear=True), patch.object(tts.urllib.request, "build_opener", side_effect=AssertionError("dry-run 不能联网")):
            assert tts.render(plan, out / "audio", dry_run=True)["clips"] == 3
        with patch.dict(os.environ, {"VOLC_TTS_API_KEY": "offline-fake-key"}, clear=True), patch.object(
                tts.urllib.request, "build_opener", return_value=Opener()) as network:
            tts.render(plan, out / "audio")
            assert network.call_count == 3
            tts.render(plan, out / "audio")
            assert network.call_count == 3, "重复渲染应复用已完成请求"
            contextual = copy.deepcopy(plan)
            contextual["clips"][1]["reference_text"] = contextual["clips"][0]["text"]
            tts.render(contextual, out / "audio")
            assert network.call_count == 4, "改上文只重新调用受影响段"
            tts.render(contextual, out / "audio")
            assert network.call_count == 4, "相同上文与指令应复用缓存"
            changed = copy.deepcopy(plan)
            changed["clips"][0]["pause_after_ms"] = 500
            tts.render(changed, out / "audio")
            assert network.call_count == 4, "停顿调整不应重新调用"
            with wave.open(str(out / "audio/final.wav"), "rb") as wav:
                assert wav.getnframes() == 3 * 240 + 12000
            changed["clips"][0]["direction"] = "低声说"
            with patch.object(tts.urllib.request, "build_opener", side_effect=OSError("模拟断网")):
                fails(lambda: tts.render(changed, out / "audio"), "断网应停止")
            before = network.call_count
            fails(lambda: tts.render(changed, out / "audio"), "不自动重发结果不确定的请求")
            assert network.call_count == before
        assert "offline-fake-key" not in (out / "audio/manifest.json").read_text()
        assert "offline-fake-key" not in (out / "audio/requests.json").read_text()
    clone_checks(plan, frames, pcm)
    timestamp_checks()
    timestamp_review_checks()
    mixed_checks()
    print("PASS：中文校对、中英混读、发音表/品牌提示/缩写/型号、原文与英语词时间戳保留、纠音冲突、语音指令与引用上文、方言、断流、预览、预置/克隆资源接线、WAV与新旧缓存、字幕晚到与脱敏、逐字时间线、句级 SRT、字幕开关与降级、十项时间戳评审回归")


if __name__ == "__main__":
    demo()
