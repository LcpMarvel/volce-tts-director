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

`speech_rate` 为整数 -50～100（0 为正常）；`pause_after_ms` 为本地拼接停顿，0～30000 毫秒；`direction` 写中文导演说明。请求输出 24kHz 单声道 PCM，使用 Python 标准库包装成 WAV、顺序拼接，无需 ffmpeg。正式调用保存无凭据的请求、请求 ID、服务端 logid、用量与耗时。字幕未实现，不虚构时间戳。

输出目录必须由当前任务独占。`render` 顺序调用，先验证全部段，再调用 API；完成段按实际请求内容复用。`manifest.json` 的 `uncertain` 表示调用结果不确定，默认不再次发送。先核对服务记录、预算与用户授权，只有允许再调用时加 `--retry-uncertain`。不要在同一输出目录同时启动两个 render。

本实现保守要求流式完成码 `20000000`、非空偶数字节 PCM；没有完成码的流不会发布为成功。错误停止，保留已完成片段，不静默重试。阅读稿始终是审稿材料，是否已生成以音频目录的 manifest 为准。

在源码仓库根目录执行本地检查（安装后的 skill 不包含开发测试）：

```sh
uv run --with pypinyin==0.55.0 python tests/selfcheck.py
```

协议依据（2026-09-30 核对）：[火山官方 HTTP 接口](https://docs.volcengine.com/docs/DoubaoVoice/unidirectional-streaming-text-to-speech-http?lang=zh)；候选词典行为：[pypinyin 官方文档](https://github.com/mozillazg/python-pinyin/blob/master/docs/usage.rst)。本工具不保证词典完整或模型遵循指令，正式生成后仍需试听多音字所在句。

## 已有克隆音色

本工具支持使用已训练完成且账号有权限的**声音复刻 2.0** 音色合成，不提供录音上传、音色训练、升级或旧代际接口。`S_` 前缀只用于识别克隆 ID 格式，不能据此断言训练代际；本工具默认选择 `seed-icl-2.0`，不自动试其他收费资源。

```sh
uv run scripts/tts.py prepare --text-file 原稿.txt --voice S_xWSg2NNT1 --resource-id seed-icl-2.0 --out plan.json
# 完成 readings 语境校对后，按常规 preview → dry-run → 已授权 render 流程执行
```

`--resource-id` 可省略：`zh_` 默认 `seed-tts-2.0`，`S_` 默认 `seed-icl-2.0`。每段可在计划中显式填写 `resource_id`，音色/资源错配或未知资源在联网前拒绝。克隆草稿写入所选资源并将 `direction` 留空，不自动假设支持普通话风格或语音指令；用户明确设置的控制字段不会静默删除。指令、上文、字典、方言的效果仍依具体训练版本和音色能力验证。

阅读稿展示资源；dry-run 的 JSON 结果和 `routes.json` 包含逐片段 `clip`、`speaker`、`resource_id` 与固定 `endpoint`，不包含密钥；`requests.json` 保持请求体数组格式。dry-run 不联网、不读取密钥，但会写本地检查文件，不能证明音色已训练或账号有权限。正式请求使用 `X-Api-Resource-Id` 选择资源，不使用旧版 `cluster`。

克隆缓存绑定端点、资源及请求体。预置资源保持原有请求体指纹，旧完成缓存继续复用，旧 `uncertain` 仍阻止重发；显式填写相同默认资源不会触发重复合成。若发现来源不明、未绑定资源的旧克隆记录，停止并要求核对，不错误复用或重新扣费。

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
