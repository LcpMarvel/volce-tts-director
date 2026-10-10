# 中英混读与发音表

## 官方参数依据（2026-10-10 核对）

- [官方音色表](https://docs.volcengine.com/docs/6561/1257544)将 `zh_male_youyoujunzi_uranus_bigtts` 列为“悠悠君子 2.0”，支持指令遵循，说明中文音色亦具备英语能力。不是旧 1.0 的 `zh_male_M100_conversation_wvae_bigtts`。
- [当前 HTTP 文档](https://docs.volcengine.com/docs/DoubaoVoice/unidirectional-streaming-text-to-speech-http)使用 `/api/v3/tts/unidirectional`、`X-Api-Resource-Id: seed-tts-2.0`；`additions.explicit_language: "zh-cn"` 表示中文为主、支持中英混读，`en` 用于英语。
- [历史 v3 HTTP 完整参数表](https://docs.volcengine.com/docs/6561/1598757)说明省略 `explicit_language` 时正常中英混读。新混读计划显式填 `zh-cn`，独立英文稿填 `en`；含中文的片段拒绝强制 `en`。不把 `zh` / `cn` 等非文档枚举传给 API，不设置 `context_language` 或额外自动语种识别。
- TTS 2.0 / ICL 2.0 中英文字幕使用 `audio_params.enable_subtitle`，而非流式 TTS 1.0 的 `enable_timestamp`。接口返回英语词级时间，不能保证每个字母或音素都有时间。
- 当前 HTTP 支持 `additions.pronunciation_dict.tone` 字符串数组，官方示例是 `北京/(bei3)(jing1)` 和 `omg/oh my god`。括号是普通话拼音，不是英语 IPA/CMU；英语品牌读音提示通过支持音色的 `context_texts` 首条提交，只是非确定性指令。本工具继续不用 SSML。

## 默认表与自定义表

默认文件为本目录的 [pronunciations.json](pronunciations.json)，随 skill 安装。可复制后修改：

```sh
uv run scripts/tts.py prepare --text-file 原稿.txt \
  --voice zh_male_youyoujunzi_uranus_bigtts \
  --pronunciation-table 我的发音表.json --out plan.json
```

省略 `--pronunciation-table` 时，含英文的稿件使用默认表；纯中文/数字稿保持原行为，不自动把中文价格中的小数改成英语。显式指定表则按用户配置应用。表内容快照保存到 `plan.pronunciation_table`，不是外部路径；preview/render 只读取计划。外部文件后续改变不会污染已审稿计划。修改已有作品时编辑计划中的表，再 preview/dry-run；缺该字段的旧计划保留原来的规则，不自动加品牌提示。

```json
{
  "version": 1,
  "words": {
    "Anthropic": "an-THROP-ik",
    "Claude": "klawd",
    "Haiku": "HIGH-koo",
    "DeepSeek": null,
    "OpenAI": null,
    "OpenRouter": null,
    "token": null,
    "cache": null
  },
  "acronyms": {
    "KV": "K V", "API": "A P I", "MLA": "M L A",
    "GPU": "G P U", "IPO": "I P O", "S-1": "S one"
  },
  "models": ["5.5", "V4.1"],
  "decimal_point": "点"
}
```

全部五个字段必需，`version` 为整数 1；未知字段、重复项、同词同时设置提示和转写、非法类型都会报错。欲仅用原生英语，可将 `words / acronyms` 置空对象、`models` 置空数组（仍保留其他字段）。

| 字段 | 实际处理 | 边界 |
| --- | --- | --- |
| words 中的英语字符串 | 仅正文出现的词的提示合入 `context_texts`，不进入 `text` | 英语可读提示，不是音素 API；最多 200 字符，不允许中文音译；源词不含空格、最长 128 字符 |
| words 中的 null | 保留原生英语，预览显示，不增加请求字段 | DeepSeek/OpenAI/OpenRouter/token/cache 默认如此 |
| acronyms | 服务端 `原词/英文目标文本`，如 `KV/K V` | 源词最多 9 字符，英文大写/数字/短横线，目标本地上限 500 字符 |
| models | 显式型号转写，`V4.1-Flash` 只控制 `V4.1`，`-Flash` 原文保留 | 最多 9 字符，可带 V/v 前缀、一个或多个数字点段；不自动推断金额/日期/IP |
| decimal_point | `point`：`5.5/five point five`、`V4.1/V four point one`；`点`：`5.5/5点5`、`V4.1/V 4点1` | 整数英语按数值读，前导零与小数部分逐数字读 |

面向中文用户，默认 `decimal_point: "点"`，例如 Haiku 5.5 按“五点五”读；V4.1 的数字部分按“四点一”读，字母和英文品牌保持英语。需要全英文型号读法时仍可改为 `point`。

型号表可加入 `V4.2`、`12.3` 等。不要只给全局 `.` 配规则；也不要把所有数字自动翻译成英文。相同的 `5.5` 出现在型号与价格两个位置时，全局字典无法分辨意图，须删去该型号规则或自然拆段。

## 请求保持原文

下面演示可选的 `point` 配置；默认中文“点”使用 `5.5/5点5` 与 `V4.1/V 4点1`。

```json
{
  "req_params": {
    "text": "Claude Haiku 5.5 比 DeepSeek V4.1-Flash 便宜，API 可用。",
    "speaker": "zh_male_youyoujunzi_uranus_bigtts",
    "audio_params": {"format": "pcm", "sample_rate": 24000, "speech_rate": 0, "enable_subtitle": true},
    "additions": "{\"disable_markdown_filter\":true,\"explicit_language\":\"zh-cn\",\"pronunciation_dict\":{\"tone\":[\"5.5/five point five\",\"API/A P I\",\"V4.1/V four point one\"]},\"context_texts\":[\"以下仅为发音提示，不朗读提示本身：英文词 Claude 按英语读作 klawd；Haiku 按英语读作 HIGH-koo。\"]}"
  }
}
```

`additions` 必须是 JSON **字符串**。英文仍在 `req_params.text` 中，没有客户端中文音译或英语近音替换；型号/缩写的文本转写发生在服务端。它不是仅改变音素而保持服务端字幕原拼写的保证。原有经授权的汉字 `spoken_alias` 是独立功能，不被此约定取消。

只编译正文当前段实际出现的规则；引用上文不触发正文规则。字典按官方规则从左到右贪心最长匹配，总计最多 5000 条，源词不超过 9 字符、不能有空格或重复。匹配本地按大小写区分和 ASCII 词界判断，汉字紧邻英文仍可命中。`API` 不应命中 `OpenAPI`，`5.5` 不应命中 `15.5`，`S-1` 不应命中 `S-10`。

如果一个源词同时以独立词和别的词的子串出现，脚本模拟完整合并字典的最长匹配，拒绝误改；只有更长明确规则确实保护该位置才允许。只出现嵌入词时不自动生成该短词规则。与手工 `clip.pronunciation_dict` 同词同目标去重、不同目标报错；仍校验全部已审阅汉字位置，不让英文转写覆盖中文纠音。

仅适用的规则进入请求指纹，表中未用词、键顺序和 native 项不触发多余合成。修改有效提示、型号读法或缩写规则会更新受影响段指纹；停顿调整仍只拼接，不自动重试不确定请求。

## 时间戳与真实测试

英语词保留服务端 `word / startTime / endTime / confidence`，不拆成估算的单字母时间。`words.json / timeline.json / final.srt` 继续导出；原稿保存在 `timeline.clips[].text`，`subtitle_text` 和 SRT 是真实返回文字，可能出现 `five / point / five` 等转写。

2026-10-10 首次在用户授权范围内，对原句使用悠悠君子 2.0、`zh-cn`、当时的 `point` 版发音表与开启字幕做了 **1 次请求**（下列记录保留该版实际结果，不代表后续中文“点”版）：

> Anthropic 发布 Claude Haiku 5.5，输入每百万 token 零点一美元，比 DeepSeek V4.1-Flash 还便宜。

结果：原文请求保持 74 字符；WAV 为 24kHz 单声道、9.981 秒；返回 28 个 timed token、3 个服务端句子。Anthropic、Claude、Haiku、token、DeepSeek 均有英语词时间戳；型号字幕实际展开为 `five point five` / `V four point one-Flash`。脱敏原始响应的 words 与 sidecar 完全一致，时间线/字幕已导出，产物未含 API key。

**这不是主观发音或精确对齐验收。** 没有音频听辨证据，不声称品牌提示已精确执行或语流自然。服务端 `DeepSeek` 与 `one-Flash` 仅约 30ms、置信度分别约 0.264 / 0.243，末词结束到 WAV 尾部约 0.466 秒；这些是供应商对齐质量观察，不能改成伪造时间或自动重发。字幕对齐使用方应试听和核对这些低置信度区间。

真实 WAV、阅读稿、脱敏响应与 acceptance.json 在本地忽略目录 `outputs/mixed-20261010-test/`，不随 skill 发布。密钥始终只从运行时 `VOLC_TTS_API_KEY` 读取，不在代码、计划或日志中存储。

同日用户反馈：Haiku 5.5 对中文用户应读“五点五”。默认表及示例计划已改为 `decimal_point: "点"`，对同一句仅追加 **1 次请求**，保留旧版音频。新版 WAV 为 8.977 秒、28 个 timed token；实际服务端字幕为 `Claude Haiku 5点5` 与 `DeepSeek V 4点1-Flash`，原文请求仍保留 `5.5 / V4.1-Flash`，供应商 words 与落盘完全一致。新版产物在 `outputs/mixed-20261010-zh-point/`；用户随后确认该版“可以的”。助手未独立试听，不把字幕中文化或一次用户认可推广为所有品牌/音色的发音保证。
