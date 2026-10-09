# 运行与计划格式

在 skill 目录执行（其他目录用脚本绝对路径）：

```sh
uv run scripts/tts.py prepare --text-file 原稿.txt --out plan.json
uv run scripts/tts.py preview --plan plan.json --out 阅读稿
uv run scripts/tts.py render --plan plan.json --out 音频 --dry-run
# 仅在用户已授权合成后；运行时环境提供 VOLC_TTS_API_KEY
uv run scripts/tts.py render --plan plan.json --out 音频
```

`prepare` 不改动原文，尽量按句末分段；生成的多音字全部为 `pending`。`preview` 允许待校对项；`render`（包括 dry-run）要求扫描候选全部有已校对标注。不要简单批量把 pending 改为 reviewed：先校对实际语境。数字拼音用于请求，阅读稿自动转成声调符号；轻声的校对记号用 `5`，ü 用 `v`，如 `lv4`；普通轻声优先 `delivery: native`，详见 [轻声与自然语流](#轻声与自然语流)。

计划唯一来源为 JSON：

```json
{
  "title": "中文阅读",
  "clips": [{
    "id": "001",
    "role": "旁白",
    "text": "银行的行长来了。",
    "voice": "zh_female_vv_uranus_bigtts",
    "direction": "温和、清楚，自然叙述，不逐字重读。",
    "reference_text": "谁来了？门口怎么这么热闹？",
    "section_id": "opening",
    "speech_rate": 0,
    "pause_after_ms": 300,
    "readings": [
      {"start": 0, "text": "银行", "pinyin": ["yin2", "hang2"], "status": "reviewed", "note": "金融机构"},
      {"start": 3, "text": "行长", "pinyin": ["hang2", "zhang3"], "status": "reviewed", "note": "银行负责人"},
      {"start": 5, "text": "来", "pinyin": ["lai2"], "status": "reviewed", "delivery": "native", "note": "普通话常用读音"},
      {"start": 6, "text": "了", "pinyin": ["le5"], "status": "reviewed", "delivery": "native", "note": "句末语气助词，保留自然语流"},
      {"start": 2, "text": "的", "pinyin": ["de5"], "status": "reviewed", "delivery": "native", "note": "结构助词，保留自然语流"}
    ]
  }]
}
```

上面仅演示字段；实际候选以扫描结果为准。标注可覆盖单字或词组，不能重叠。每个词组最多 9 个汉字，每个字一个拼音。替换词组标注时删除已覆盖的单字标注。请求采用官方 `additions` JSON 字符串里的 `pronunciation_dict.tone`，例如 `银行/(yin2)(hang2)`；同词规则去重，并模拟贪心最长匹配，验证每个已校对位置实际得到指定读音。显示注音不改变 `req_params.text`；已授权的客户端可听别名除外。

只允许官方固定端点 `https://openspeech.bytedance.com/api/v3/tts/unidirectional`，资源限定 `seed-tts-2.0`（`zh_` 预置音色）和 `seed-icl-2.0`（`S_` 已有克隆音色），不隐式代理到其他供应商。可用音色以用户控制台权限为准；离线检查只验证 ID 格式和本工具的资源组合，不能证明账号权限、训练状态或中文发音效果。

`speech_rate` 为整数 -50～100（0 为正常）；`pause_after_ms` 为本地拼接停顿，0～30000 毫秒；`direction` 写中文导演说明。请求输出 24kHz 单声道 PCM，使用 Python 标准库包装成 WAV、顺序拼接，无需 ffmpeg。正式调用保存无凭据的请求、请求 ID、服务端 logid、用量与耗时。默认启用逐字字幕，输出片段 `*.words.json`、全片 `timeline.json` 和句级 `final.srt`；未返回字幕时明确标记，不虚构时间戳，详见 [逐字时间戳与字幕](#逐字时间戳与字幕)。

输出目录必须由当前任务独占。`render` 顺序调用，先验证全部段，再调用 API；完成段按实际请求内容复用。`manifest.json` 的 `uncertain` 表示调用结果不确定，默认不再次发送。先核对服务记录、预算与用户授权，只有允许再调用时加 `--retry-uncertain`。不要在同一输出目录同时启动两个 render。

本实现保守要求流式完成码 `20000000`、非空偶数字节 PCM；没有完成码的流不会发布为成功。错误停止，保留已完成片段，不静默重试。阅读稿始终是审稿材料，是否已生成以音频目录的 manifest 为准。

在源码仓库根目录执行本地检查（安装后的 skill 不包含开发测试）：

```sh
uv run --with pypinyin==0.55.0 python tests/selfcheck.py
```

协议依据（2026-09-30 核对）：[火山官方 HTTP 接口](https://docs.volcengine.com/docs/DoubaoVoice/unidirectional-streaming-text-to-speech-http?lang=zh)；候选词典行为：[pypinyin 官方文档](https://github.com/mozillazg/python-pinyin/blob/master/docs/usage.rst)。本工具不保证词典完整或模型遵循指令，正式生成后仍需试听多音字所在句。

## 逐字时间戳与字幕

TTS 2.0 / ICL 2.0 使用 `audio_params.enable_subtitle`，不是 1.0 的 `enable_timestamp`。默认开启；优先级是 CLI `--timestamps / --no-timestamps` > clip `enable_subtitle` > 顶层 `enable_subtitle` > true。字段只接受 JSON 布尔值，不接受 `"true"` 或数字。

```json
{
  "enable_subtitle": true,
  "clips": [
    {"id": "001", "text": "你好。", "voice": "zh_female_vv_uranus_bigtts",
     "readings": [{"start": 1, "text": "好", "pinyin": ["hao3"], "status": "reviewed", "delivery": "native"}]}
  ]
}
```

```sh
uv run scripts/tts.py render --plan plan.json --out 音频 --timestamps --dry-run
# 已授权后，只发送计划内请求，不自动重试
uv run scripts/tts.py render --plan plan.json --out 音频 --timestamps
# 可选：核对响应 JSON 行，不打印密钥、请求头或 base64 音频
uv run scripts/tts.py render --plan plan.json --out 调试音频 --timestamps --debug-stream
```

HTTP 使用顶层 `sentence: {text, words, phonemes}`，`words` 词条为 `{word, startTime, endTime, confidence}`；时间单位秒，相对本次请求起点。`phonemes` 不用于推断未返回的字词时间。音频与字幕可在同帧，字幕也可能在最后音频之后；脚本要求完成码 `20000000` 并读取到响应 EOF。实际末帧与字幕顺序应通过真实响应核对，不把 WebSocket 格式或一次请求的顺序当作所有响应的保证。

输出结构：

- `<hash>.words.json`：`text` 为服务端字幕文字（无字幕时为实际提交文字），`words` 保留原始片段秒时间，`sentences` 保存句级文字与所属字词的真实首尾时间。累计帧的字词/标点/时间修订只有在词汇与时间覆盖关系可可靠识别时替换旧组，含糊的部分重叠降级；不虚构服务端句子 ID。字幕中文字可能附标点、体现数字转写或可听别名，不强制拆成单一字符，也不将原稿强行映射到服务端字词。
- `manifest.json` 请求条目：`words_file` 为相对输出目录的文件名，`timestamps` 为可用字词时间状态，`timestamps_reason` 为空或 `disabled / explicit_dialect / enable_latex_tn / not_returned / invalid_subtitles`。
- `timeline.json`：`sample_rate: 24000`、`duration` 为最终 WAV 秒长度；`clips` 中含 `id / text / subtitle_text / offset / duration / pause_after_ms / audio / words_file / timestamps / timestamps_reason`。顶层 `words / sentences` 的 `startTime / endTime` 已加上该段 `offset`，并增加 `clip` ID。偏移严格按 PCM 采样数累计，包含全部本地段后停顿（包括最后片段），修改停顿不改变每段 words 文件。
- `final.srt`：用返回文字的中文句末标点分句，按唯一连续字词归属取真实首尾时间，无假字幕填补停顿。跨句 token 合并字幕，不拆其时间；零时长标点允许附属于一个正时长句子，整句零时长无效。数字规范化等不能逐字对应时，只有真实文字锚点能唯一确定句界才保留分句，否则保留服务端整句时间。全无字幕时生成空文件，不捏造字幕。字词归属仅为本地内部索引，公开 JSON 格式不增加必需字段；旧 sidecar 仍可读取。

`timeline.timestamps` 只有全部片段都有字幕才为 true；混合片段仍保留可用字词，不把没有字幕的音频时长省略出偏移计算。方言 `explicit_dialect`、片段 `enable_latex_tn: true` 与字幕不兼容，自动将该请求的字幕开关设为 false（LaTeX 开关本身传入 additions）；无字幕/无效字幕正常输出 WAV 和空字词文件，并在 manifest 标记原因。不为补齐字幕自动重试或换资源。

缓存指纹包含有效字幕开关，旧无开关指纹不会直接命中。开启字幕遇到旧完成缓存缺 words 文件，或当前完成缓存丢失 words 文件时，在整个计划联网前停止，明确提示需要重新渲染。核对费用和授权后用新的输出目录；不删除旧缓存，不自动重发。旧无开关 `uncertain` 也不能被新指纹静默绕过。正常无字幕的空 words 文件可复用，避免重复收费；manifest 标记 `timestamps: true` 却变成空 sidecar 时须拒绝，不能静默改为 false。历史记录缺少字幕状态时兼容迁移为实际可用状态，不自动请求补齐。全部已完成 WAV 和字幕缓存会在任何新调用前预检；损坏 JSON、截断/无效音频、句级文字错配字词时间等都会明确拒绝，不先调用前段再发现后段损坏。已有句子直接校验，不重新构造后丢弃；缺 sentences 的旧 sidecar 只兼容生成并保存一次。字词与句子时间须能表示为有限数值、非负、有序，并在实际片段 PCM 时长内（容许 10ms 时间量化误差，不裁剪）；句级时长须为正。新响应的无效字幕降级为 `invalid_subtitles`，无效缓存则提示需要重新渲染；两者都不自动请求补齐。

WAV 预检按固定块读取全部声明 PCM 验证完整性，缓存只保留文件路径、帧数和字幕，不保留音频字节；最终 WAV 与长停顿也分块写入临时文件，完成后原子替换。未变化或仅修改停顿的缓存渲染不重写 manifest/相同字幕文件；旧元数据迁移批量保存。真实 API 调用仍在请求前即时保存 uncertain、音频和字幕文件写完后保存 complete，异常即时记录，不能为了减少写入而省略这些持久化检查点。

时间戳的对齐精度由火山接口负责。本工具保留返回字词的原始 `startTime / endTime / confidence`，只做协议/结构校验、缓存保存、本地拼接偏移与 SRT 毫秒格式转换；不修改服务端字词时间、不裁剪音频、不引入强制对齐或其他精度补偿。`timestamps: true` 只表示字幕可解析和导出，不是精确口型保证。

短句真实接口测试检查响应完整、接口字词与落盘原始值一致、时间线偏移和 SRT 导出正确；`words` 非空、时间有限且单调用于确认结构可用。最后 `endTime` 与 WAV 时长差（例如 0.3 秒参考值）、低 confidence 等另行记录为供应商对齐质量观察，不作为本工具请求/导出成功的必达条件。无字幕、服务质量观察或请求失败都应如实报告，不自动重试、修正或把观察项冒充实现错误。旧验收报告保留当时的检查结果，不改写历史以宣称通过；结构检查也不证明已试听或口型精度。

协议依据：[官方 HTTP 字幕参数与 sentence 响应](https://docs.volcengine.com/docs/DoubaoVoice/unidirectional-streaming-text-to-speech-http?lang=zh)、[完成码与流式响应示例](https://www.volcengine.com/docs/6561/1598757)。

## 已有克隆音色

本工具支持使用已训练完成且账号有权限的**声音复刻 2.0** 音色合成，不提供录音上传、音色训练、升级或旧代际接口。`S_` 前缀只用于识别克隆 ID 格式，不能据此断言训练代际；本工具默认选择 `seed-icl-2.0`，不自动试其他收费资源。

```sh
uv run scripts/tts.py prepare --text-file 原稿.txt --voice S_xWSg2NNT1 --resource-id seed-icl-2.0 --out plan.json
# 完成 readings 语境校对后，按常规 preview → dry-run → 已授权 render 流程执行
```

`--resource-id` 可省略：`zh_` 默认 `seed-tts-2.0`，`S_` 默认 `seed-icl-2.0`。每段可在计划中显式填写 `resource_id`，音色/资源错配或未知资源在联网前拒绝。克隆草稿写入所选资源并将 `direction` 留空，不自动假设支持普通话风格或语音指令；用户明确设置的控制字段不会静默删除。指令、上文、字典、方言的效果仍依具体训练版本和音色能力验证。

阅读稿展示资源；dry-run 的 JSON 结果和 `routes.json` 包含逐片段 `clip`、`speaker`、`resource_id` 与固定 `endpoint`，不包含密钥；`requests.json` 保持请求体数组格式。dry-run 不联网、不读取密钥，但会写本地检查文件，不能证明音色已训练或账号有权限。正式请求使用 `X-Api-Resource-Id` 选择资源，不使用旧版 `cluster`。

克隆缓存绑定端点、资源及请求体；预置资源按请求体生成指纹。请求体现在显式包含字幕开关，不能命中缺少该字段的旧音频缓存；开启字幕遇到缺 words 文件的旧完成缓存时先停止并提示重渲染，旧 `uncertain` 仍阻止静默重发。显式填写相同默认资源不会触发重复合成。若发现来源不明、未绑定资源的旧克隆记录，停止并要求核对，不错误复用或重新扣费。

首次用新克隆音色时先试听一段短中文。权限、训练代际或网络出错时保留实际状态，不自动重试、切换资源或训练。成功与否以服务返回和 manifest 为准，实际演绎和相似度须试听，不能用结构检查代替。

## 语音指令与引用上文

依据 [官方语音指令与标签说明](https://docs.volcengine.com/docs/DoubaoVoice/DoubaoTextToSpeech20CapabilityIntroduction?lang=zh)：语音指令控制情绪、方言、语气、语速和音调；引用上文帮助承接语境，只引用不合成。[官方 HTTP 接口](https://docs.volcengine.com/docs/DoubaoVoice/unidirectional-streaming-text-to-speech-http?lang=zh) 提供 `additions.context_texts`，仅支持相应 2.0 音色；方言另有 `additions.explicit_dialect`，需要支持对应方言的音色。具体支持情况以 [官方音色列表](https://docs.volcengine.com/docs/DoubaoVoice/Tonelist-1?lang=zh) 为准，脚本的音色 ID 格式检查不能替代能力检查。

| 计划字段 | 用法 | 实际请求 |
| --- | --- | --- |
| direction | 中文语音指令，如“用兴奋但克制的语气，稍慢地说” | 合入 context_texts 首条 |
| reference_text | 当前台词之前的真实中文上文；省略或空字符串表示无引用 | 加“只用于理解并承接语境与情绪，不朗读”说明，合入 context_texts 首条 |
| explicit_dialect | 官方方言代码；省略或空字符串表示随音色默认 | additions.explicit_dialect |
| speech_rate | -50～100 的整数；0 正常，-50 为 0.5 倍速，100 为 2 倍速 | audio_params.speech_rate |

`reference_text` 是本工具的计划字段，当前官方 HTTP 文档未列出独立的引用上文参数；这里通过自然语言语境说明接入 `context_texts`，不向 API 发送自创字段。语音指令、上文和纠音说明合为一个字符串，避免后续数组项被忽略；不把官方控制台展示的 `[#...]` 标记拼进正文，也不使用 SSML。

上文从原稿或实际对话中选取，只保留与当前片段有关的部分。跨角色可引用前一位说话人的台词；跨场景不要自动沿用。`prepare` 不猜测关系，默认引用为空，由导演结合原稿填入。上文本地上限为 500 字，是本工具策略而非官方限制；超过时明确选取必要前文，不静默截断。阅读稿分别展示语音指令和引用上文，正文仍保留原稿；上文没有口播读音标注要求。

方言代码：`beijing` 北京话、`dongbei` 东北话、`henan` 河南话、`shaanxi` 陕西话、`shanghai` 上海话、`sichuan` 四川话、`tianjin` 天津话、`yue` 粤语。方言请求应选相应音色，并删除“普通话”类冲突指令。普通话拼音不用于强制方言发音；这类片段可保留 `native` 展示校对，实际方言效果以试听为准。

例如以下是合成片段的控制字段（其余字段照计划格式填写）：

```json
{
  "direction": "带着惊喜，稍慢地说，承接久别重逢的情绪。",
  "reference_text": "是你吗？好久没见了！",
  "speech_rate": -10
}
```

本地验证能确认上文未进入 `req_params.text`、说明与纠音同时提交、修改上文会更新受影响段缓存；不能证明服务端不串读上文或真实情绪承接。首次使用某音色时，优先试听一个有上文和无上文的代表句，检查是否只朗读正文、情绪是否承接、多音字是否正确。真实调用遵从已有授权范围，不自动为每次改指令反复抽样。

## 段落标识 section_id

在片段设置 `"section_id": "opening"` 后，脚本传入 `additions.section_id`。省略或空字符串时不传。依据官方文档，该参数为字符串，用于配置段落标识、保持跨包语义，适用于语音合成 2.0 和声音复刻 2.0；本工具可用于预置与已有克隆音色，实际效果须验证。

连续段落被拆成多个合成片段时可以沿用同一标识；场景切换时换标识。它不是引用上文的替代，不把段落标识当作服务端跨请求记忆、音色一致性或连贯性的保证。阅读稿显示标识，缓存绑定真实字段；账号效果仍需实际验收。

## 火山专用纠音方式与实际验证

火山的纠音不能仅靠导演提示词或页面注音。当前脚本已接上 `additions.pronunciation_dict.tone` 的括号拼音规则，例如 `还款/(huan2)(kuan3)`；`additions` 本身须为 JSON 序列化字符串。裸写 `还款/huan2 kuan3` 不是本工具采用的发音格式。

发音字典同时支持“原词/目标文本”的服务端文本转写。片段可补充以下字段；脚本与 `readings` 生成的规则合并，仍通过 JSON 序列化字符串 `additions` 提交：

```json
{"pronunciation_dict":{"tone":["北京/(bei3)(jing1)","123/一百二十三"]}}
```

本工具只做中文：原词限 1～9 个中文或数字字符，转写目标须为中文，目标文本本地上限 500 字。规则原词不可重复，合并后最多 5000 条；与位置注音对同一词的相反规则会报错。补充字典不自动把多音字候选标为已校对。按实际提交文本模拟贪心最长匹配，检查全部已校对位置：转写跨到已校对位置时，本工具要求等长且替代字读音唯一、符合目标；不同长度需先明确口播改写并重新校对。只涉及数字等无位置注音的部分允许不同长度转写。

服务端字典对本请求中所有匹配原词生效，`req_params.text` 保持原稿；客户端 `spoken_alias` 按单个位置替字，实际提交文本已经变化。两者都在阅读稿中显示，不能混称。英文转写示例属于官方接口能力，本中文 skill 不接入英文。

用户已明确 SSML 在其实际场景不可用。本 skill 不使用 SSML，也不把它列为纠音后备；停顿使用本地音频编排，读音可以保持原生、使用字典、指令，或已授权的可听别名加指令。

`reviewed` 只表示读音已按语境校对；本地检查只证明标注、字典格式及匹配接线正确。是否真正生效须用实际音色合成并试听，服务端返回成功、ASR 转写正确都不能独立证明多音字读对。用户有既往失败原句时优先用于小范围试听验收，保持真实合成在已授权范围内；没有试听证据不得宣称问题已解决。

## 纠音投递方式

先按语境确定目标读音，再选择实际投递方式。页面注音只用于审稿，不会自动传给合成服务；读音决定正确不等于执行通道有效。

难读姓氏或专名在原生读法、字典或指令效果不稳定时，可使用已获授权的可听别名：保留稿面与 `text` 原字，仅按标注位置替换实际提交文本，同时附目标读音指令。例如“华老栓忽然坐起身”中的姓氏“华”读 `hua4`，可提交“桦老栓忽然坐起身”，并附 `hua4` 指令；“花”读 `hua1`，不能作为替代。导演说明与全部纠音说明合入第一条 `context_texts`，避免后续说明未生效。

单独替字仍可能随音色或单次生成而偏音，因此采用“别名 + 指令”后仍须试听。一个词应按具体位置处理，不能全局替换；阅读稿同时显示原字、目标读音和实际替代字，便于用户检查。

每项 `readings` 可选：

| delivery | 实际请求 | 用途 |
| --- | --- | --- |
| native | 不发送纠音要求 | 普通读法仅做展示，避免无意义过度覆盖；prepare 默认 |
| dictionary | 发音字典括号拼音 | 明确词组控制；旧计划省略 delivery 时沿用此方式 |
| instruction | 原文加读音指令 | 不替字，指令可能被忽略，需试听 |
| spoken_alias | 按位置替字，同时加读音指令 | 已获授权的具体替代映射 |

该句的“华”标注示例：

```json
{"start":0,"text":"华","pinyin":["hua4"],"status":"reviewed","delivery":"spoken_alias","spoken_alias":"桦","alias_approved":true,"note":"姓氏第四声；已授权仅对本位置使用可听替换"}
```

`text` 仍为原稿，脚本不全局 replace。别名目前限等长汉字，每字词典读音必须唯一且逐音节等于目标读音；“花/hua1”不能替代“华/hua4”。已校对但尚未授权替字的项可以使用 instruction 或 dictionary；不得自行把授权字段置真。所有导演与纠音说明合入一条 `context_texts`，预览列出实际处理方式，缓存按真实提交文本和指令变化。字典覆盖别名或其他已校对位置时会报错。

### 轻声与自然语流

普通轻声助词先保留自然语流。`readings` 仍按语境填写 `de5`、`le5` 等，并完成校对，但明确设置 `delivery: native`，不自动加入发音字典或逐字轻声指令。旧计划省略 `delivery` 会走 `dictionary`，不能只改页面注音或删除导演提示；还要检查实际请求的 `pronunciation_dict.tone`，包括补充字典中的相关规则。

例如“长得差不多”中的局部标注（其他扫描项仍须校对）：

```json
{"start":0,"text":"长得","pinyin":["zhang3","de5"],"status":"reviewed","delivery":"native","note":"生长外形；得为轻声补语助词，实际保留自然连读"}
```

只有实际错读或用户明确要求纠音时，才尝试更具体的词组规则或指令；不因词典列出多读音就强制标注。若用户反馈轻声别扭、词组断连，先用同一音色、原句和语速生成短样，撤掉相关强制规则与轻声指令，对照试听；不要反复叠加提示词，也不要把重音、姓名、地名等必要纠音一起撤掉。真实调用仍遵从已有授权，确认有效后只重做受影响段。

实际案例（2026-09-30，Vivi 2.0）：用户试听“想象两组长得差不多的草莓”时，`长得/(zhang3)(de5)` 和再加轻声指令的两版均被反馈别扭、不连贯；撤掉该规则及轻声指令的原句短样被用户确认更连贯。这支持该句优先自然读法，不能据此断言火山不支持 `de5` 或所有轻声都禁止标注。
