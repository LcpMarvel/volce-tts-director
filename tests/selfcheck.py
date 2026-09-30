"""本地验收：真实中文校对 + 请求接线 + 模拟音频；零 TTS 调用。"""
import base64
import copy
import importlib.util
import io
import json
import os
import tempfile
import wave
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
                        ("reference_text", "English 上文"), ("explicit_dialect", "unknown"),
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
    fails(lambda: tts.prepare("Hello 中文"), "不隐式做英文")
    fails(lambda: tts.prepare("中" * 501), "不截断长句")
    pcm = b"\x01\x00" * 240
    frames = [json.dumps({"code": 0, "data": base64.b64encode(pcm).decode()}).encode(),
              b'{"code":20000000,"usage":{"text_words":9}}']
    assert tts.decode_stream(frames) == (pcm, {"text_words": 9})
    fails(lambda: tts.decode_stream(frames[:1]), "断流不能当成功")
    fails(lambda: tts.decode_stream([b'{"code":55000000}']), "错误码不能忽略")
    class Response(io.BytesIO):
        headers = {"X-Tt-Logid": "offline-check"}
    class Opener:
        def open(self, request, timeout):
            assert request.full_url == tts.ENDPOINT
            assert request.get_header("X-api-key") == "offline-fake-key"
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
        with patch.dict(os.environ, {"VOLC_TTS_API_KEY": "offline-fake-key"}), patch.object(
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
    print("PASS：中文校对、原文保留、纠音冲突、语音指令与引用上文、方言、断流、预览、请求接线、WAV与缓存")


if __name__ == "__main__":
    demo()
