# 运行与计划格式

在 skill 目录执行（其他目录用脚本绝对路径）：

```sh
uv run scripts/tts.py prepare --text-file 原稿.txt --out plan.json
uv run scripts/tts.py preview --plan plan.json --out 阅读稿
uv run scripts/tts.py render --plan plan.json --out 音频 --dry-run
# 仅在用户已授权合成后；运行时环境提供 VOLC_TTS_API_KEY
uv run scripts/tts.py render --plan plan.json --out 音频
```

`prepare` 不改动原文，尽量按句末分段；支持英文词、型号和数字（包括独立英文/数字片段），英文句界保守识别，不拆小数/型号内部点号和常见缩写。含英文时默认发音表快照写入计划，纯中文/数字稿不自动改变读法；可用 `--pronunciation-table 文件.json` 指定自定义表，格式见 [中英混读](mixed-language.md)。生成的汉字多音字全部为 `pending`。`preview` 允许待校对项；`render`（包括 dry-run）要求扫描候选全部有已校对标注。不要简单批量把 pending 改为 reviewed：先校对实际语境。数字拼音用于请求，阅读稿自动转成声调符号；轻声的校对记号用 `5`，ü 用 `v`，如 `lv4`；普通轻声优先 `delivery: native`，详见 [轻声与自然语流](#轻声与自然语流)。

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

普通 TTS 只允许官方固定端点 `https://openspeech.bytedance.com/api/v3/tts/unidirectional`，资源限定 `seed-tts-2.0`（`zh_` 预置音色）和 `seed-icl-2.0`（`S_` 已有克隆音色），不隐式代理到其他供应商。可用音色以用户控制台权限为准；离线检查只验证 ID 格式和本工具的资源组合，不能证明账号权限、训练状态或中文发音效果。

`speech_rate` 为整数 -50～100（0 为正常）；`pause_after_ms` 为本地拼接停顿，0～30000 毫秒；`direction` 写中文导演说明。普通 TTS 请求输出 24kHz 单声道 PCM，使用 Python 标准库包装成 WAV、顺序拼接，无需 ffmpeg。正式调用保存无凭据的请求、请求 ID、服务端 logid、用量与耗时。默认启用逐字字幕，输出片段 `*.words.json`、全片 `timeline.json` 和句级 `final.srt`；未返回字幕时明确标记，不虚构时间戳，详见 [逐字时间戳与字幕](#逐字时间戳与字幕)。

输出目录必须由当前任务独占。`render` 顺序调用，先验证全部段，再调用 API；完成段按实际请求内容复用。`manifest.json` 的 `uncertain` 表示调用结果不确定，默认不再次发送。先核对服务记录、预算与用户授权，只有允许再调用时加 `--retry-uncertain`。不要在同一输出目录同时启动两个 render。

普通 TTS 路由保守要求流式完成码 `20000000`、非空偶数字节 PCM；没有完成码的流不会发布为成功。错误停止，保留已完成片段，不静默重试。阅读稿始终是审稿材料，是否已生成以音频目录的 manifest 为准。

在源码仓库根目录执行本地检查（安装后的 skill 不包含开发测试）：

```sh
uv run --with pypinyin==0.55.0 python tests/selfcheck.py
```

协议依据（2026-09-30 核对）：[火山官方 HTTP 接口](https://docs.volcengine.com/docs/DoubaoVoice/unidirectional-streaming-text-to-speech-http?lang=zh)；候选词典行为：[pypinyin 官方文档](https://github.com/mozillazg/python-pinyin/blob/master/docs/usage.rst)。本工具不保证词典完整或模型遵循指令，正式生成后仍需试听多音字所在句。

## 情绪演绎模式

**v0.4.0 新增；一个 S_ 样本已完成真实协议核对，用户试听认为该冷笑短句的 perform 效果明显优于 TTS。** 官方音频生成 HTTP 页面正文已于 **2026-10-12** 在线复核（列出 18 种语言）；同日按用户授权进行了 perform / TTS 短样调用，观察见下方记录。这条试听反馈只适用于本次样本；真实返回成功、结构校验与 mock 本身不证明音色身份、发音或演绎效果。后续真实调用仍须遵守用户授权的调用次数与预算。

普通 TTS 行为不变：省略 `mode` 等于 `"tts"`，仍走 `/api/v3/tts/unidirectional`，旧请求、指纹和缓存保持不变。笑、哭出声、尖叫、叹气、冷笑、打滚喊疼等副语言，或已有 `S_` 音色的强情绪句，可手动改为 `"perform"`，走固定 `POST https://openspeech.bytedance.com/api/v3/tts/create`、`model: "seed-audio-1.0"`。预置 2.0 音色的整体情绪先试 `direction`。`prepare` 不改，模式由 Agent 在校对阶段手动标记。

新版 API 文档列出 **18 种语言**；本工具当前仅接受中文、英文及中英混读，`explicit_language` 仅为 `zh-cn / en`。这是本地验证与工作流范围，不能写成 seed-audio 模型只支持中英文；本版本也不保证纯方言，方言口音效果须试听。

### 完整字段与限制

| 字段 | perform 用法 |
| --- | --- |
| 顶层 `voices` | 可选的角色 → 音色 ID 对象；两种模式共用，见下节 |
| `id` / `role` | 唯一片段 ID（字母数字、短横线、下划线，1～64 字符）；role 用于导演说明与角色映射 |
| `mode` | 省略或 `"tts"` 为旧行为；`"perform"` 才允许 `perform` 对象，tts 携带该对象会报错 |
| `perform.prompt` | 必填、1～500 字符，写能听见的动作、顺序与语气，不包含台词；最终拼好的 `text_prompt` 不超过 3000 字符 |
| `perform.takes` | 1～4 的整数，默认 **1**；每个 take 都是独立计费调用，不自动重试 |
| `perform.selected_take` | `null`（默认）或 1～takes 的整数；takes > 1 且 null 时暂用 take 1，须人工试听后选择；takes = 1 视为 single |
| `perform.ambience` | 布尔值，默认 **false**，自动加入只要人声干声的约束；true 仅移除此约束，允许模型混合环境声，不提供分轨 |
| `voice` | 可显式填写，或按 role 从映射解析；接受有权限的 2.0 `zh_` 预置 / 已有 `S_` 复刻 ID，放入 `references[0].speaker`，不能把体验中心昵称当 ID |
| `resource_id` | 可省略；填写时仍按原规则校验与音色一致（zh_ / seed-tts-2.0，S_ / seed-icl-2.0），但不发送到 perform 请求或请求头 |
| `text` | 只存台词，最多 **400 字符**，超长明确拆段；这是本地保守策略，官方人声文本建议值不是模型语言上限 |
| `direction` | 可选字符串，作为角色整体语气放在 perform.prompt 前 |
| `reference_text` | 可选真实上文，本地上限 500 字符；加“只用于理解情绪，不要念出来”说明，仍有被模型串读风险，必须试听 |
| `speech_rate` | -50～100 的整数，0 正常，映射到 `audio_config.speech_rate` |
| `pause_after_ms` | 0～30000 的整数，本地段后停顿；不裁剪模型原有首尾静音 |
| `readings` | 扫描候选须全部按语境 reviewed；native 仅展示；instruction 转成 prompt 发音要求；已授权 spoken_alias 替换提交文本并附发音要求 |
| `readings[].delivery: dictionary` | **拒绝**，不能把 TTS 发音字典发送到 perform；旧标注省略 delivery 会默认字典，须明确改为 native / instruction / 已授权 spoken_alias |
| `pronunciation_dict` | 不支持有效发音字典规则；改用上述投递方式，或把该句留在 TTS |
| 顶层 `pronunciation_table` | 命中的 acronyms / models 字典转写拒绝，不静默删除；words 的英语读音提示转为 prompt 的发音要求，null 保留原生读法 |
| `explicit_dialect` / `enable_latex_tn` / `section_id` | perform 不支持，移除字段，不用空值或 false 当作后备；方言口音可写入 prompt，效果未验证 |
| `explicit_language` | 仅接受 zh-cn / en，本地校验后不发送；含中文不能强制为 en |
| `enable_subtitle` | 映射到 `audio_config.enable_subtitle`；CLI --timestamps / --no-timestamps > clip > 顶层 > true |
| watermark | 本版本不增加请求字段或开关；发布 AI 内容的显式标识/元数据合规须按目的地要求处理，不能以未发送字段代替合规判断 |

### 同一角色共用音色映射

计划顶层可以写：

```json
{
  "voices": {
    "旁白": "zh_male_youyoujunzi_uranus_bigtts",
    "白骨精": "zh_female_vv_uranus_bigtts"
  }
}
```

`preview / render --voices FILE` 读取同结构的**裸映射对象**（不是含 voices 键的计划）。[examples/voices.example.json](../../../examples/voices.example.json) 是买家模板：

```json
{
  "旁白": "S_替换成你的复刻音色ID",
  "白骨精": "S_替换成你的复刻音色ID"
}
```

先填自己的 ID；占位值会报“请填写自己的音色”，不是可合成 ID。**解析优先级：clip 显式 voice > CLI 文件映射 > 计划顶层映射**。CLI 按角色覆盖计划映射，未覆盖角色继续使用计划值；若片段已写死 voice，要移除它才会用角色映射。缺少角色时在联网前报错并列出缺项。解析结果进入请求体与缓存指纹，两种模式不能另配独立音色；但 ID 相同不保证听感相同，首次仍需按授权做同角色的 TTS / perform 短句 A/B 试听。

### prompt 模板与请求

Agent 只编辑字段，由脚本拼出以下模板；不要自行把注音阅读稿或整段模板复制进 text / perform.prompt。条件行只在对应字段存在时加入：

```text
“{role}”全程只用指定音色。
{role}的整体语气：{direction}
上文（只用于理解情绪，不要念出来）：{reference_text}
{role}{perform.prompt}：“{提交文本}”
发音要求：{instruction / 英语读音提示}
只生成这一个角色的人声干声，不要背景音乐、环境声或音效，不要添加台词以外的话。
```

最后一行只在 ambience=false 时加入。**使用音色 ID 时，描述里不要写 `@音频N`；声音只通过 `references[].speaker` 指定。** 这条规则同时适用于豆包 TTS 2.0 预置 `zh_` 音色与复刻 `S_` 音色，不能把音频参考标记混入 speaker 模式。示例动作可以是“先压低嗓子发出三声尖细冷笑，停半拍，再拖长尾音、低声说”；台词仍只在 text。实际提交文本只应用已授权的 spoken_alias，原稿保留。方向、上文或发音提示也可能被模型忽略或念出，preview / requests.json 只证明接线，不能替代试听。

请求体示意（非真实成功响应证据）：

```json
{
  "model": "seed-audio-1.0",
  "text_prompt": "由上述模板生成的完整字符串",
  "references": [{"speaker": "解析后的音色ID"}],
  "audio_config": {
    "format": "wav",
    "sample_rate": 24000,
    "speech_rate": 0,
    "enable_subtitle": true
  }
}
```

依据提供的文档，perform 采用 X-Api-Key（运行时 VOLC_TTS_API_KEY），可附 X-Api-Request-Id，不发送 X-Api-Resource-Id；控制台须另开通**豆包音频生成模型 1.0**及音色权限。相同密钥是否对账号可用须核对，dry-run 不读取密钥。只允许上述固定端点、拒绝重定向，顺序调用，不自动换资源、重试或并发。参考仅为 speaker ID，本版不上传参考音频、图片，也不做音色设计。

**响应规则与实测边界：**speaker 模式支持豆包 TTS 2.0 预置音色与声音复刻音色；音色只由 `references[].speaker` 指定，描述中不写 `@音频N`。不要将误用音频引用标记的请求结果当作预置音色不支持的证据；音色权限与听感应按正确参数及具体账号核对。官方 schema 列 code / message，但 HTTP 200 示例省略 code；2026-10-12 的真实 perform 响应也未包含 code，已据此修正本地处理：**仅 HTTP 200 且 audio 可解码为有效非空 WAV 时允许缺 code**；若字段存在，只接受严格整数 0 / 20000000，null、布尔、字符串及错误码均拒绝。实际观察到的是缺 code，不是上述成功码取值；HTTP 200 本身不是成功的充分条件。manifest 记录 http_status、response_code_present、response_code，区分缺字段与返回 null。请求超时暂设 300 秒（官方 curl 示例同为 --max-time 300），不保证实际生成耗时。

### 真实核对记录（2026-10-12）

仅使用一个获授权的 S_ 音色，同音色、同台词生成 perform 与普通 TTS；不披露真实音色 ID、请求 ID 或 logid，不依赖未入库的本地产物路径。

- 第一次 perform 已返回音频、duration / original_duration 均为 **6.30 秒**及匹配字幕，但没有 code；当时旧严格检查使本地失败，状态保留 uncertain，未保存音频。用户随后**另行明确授权一次重试**，没有自动重试。
- 重试 perform 为 HTTP 200、仍无 code，manifest 记录 response_code_present=false；有效 WAV 校验通过后保存。duration / original_duration 均为 **5.18 秒**，服务端 WAV 为 **24 kHz / 16-bit / 双声道**，逐帧平均下混为单声道，记 downmixed=true；不是接口保证单声道。
- 同音色、同台词的 TTS 独立成功，时长 **2.1866667 秒**；本地停顿合计 **0.70 秒**，最终 WAV **8.0666667 秒**，TTS 段 offset 为 **5.88 秒**。perform 字幕毫秒转秒并加拼接偏移已核对，两个片段 timestamps=true，perform 的 text_match=true；这些是结构/文字核对，不是听审结论。
- 整段 RMS：perform **-28.833 dBFS**、TTS **-19.567 dBFS**，差约 **9.266 dB**。此指标含静音，不等于主观响度差；未归一、未裁剪或自动修正音频。
- 共 **3 次真实调用：2 次 perform（含首次本地失败）+ 1 次 TTS**。两次 perform 的 original_duration 合计 **11.48 秒**可能计费，本地失败不意味着供应商免费；实际账单、额度消耗与 TTS 费用以控制台为准。
- **用户试听后确认该冷笑样本的 perform 效果明显优于 TTS。** 该反馈不单独证明音色身份/相似度或干声质量，也不能推广到其他场景；不从 code 缺失兼容、text_match 或 WAV 结构推断听感通过。

### takes、缓存与交付流程

1. 先校对全部 readings，preview 展示原文、导演动作、读音投递与解析后的音色；再 dry-run 审阅请求，说明收费调用上界与预算。示例 [examples/perform/plan.json](../../../examples/perform/plan.json) 是一段旁白 TTS + 一句白骨精冷笑 perform（3 takes），用于演示字段与流程，实际效果按账号权限与试听确认。
2. 用户授权后生成全部 take，不自动挑选。每条 take 独立指纹，绑定 endpoint、model、实际 body 和 1 起的 take 编号；音频与字幕按 `<fingerprint>.wav / .words.json` 缓存。另存 `takes/<clip_id>-take<k>.wav`（链接或复制）供试听，`takes.json` 列出 take、fingerprint、file、original_duration。
3. 多 take 且 selected_take=null 时，暂用 take 1 拼接，timeline 的 take_selection 为 provisional，结果列 pending_selection。用户试听后写入所选编号，在**同一输出目录**再 render，已完成 take 不重复收费，只重拼 final.wav / timeline.json / final.srt；takes=1 为 single，明确选择为 selected。
4. takes 从 2 增为 3 只新增 take 3；改 selected_take 或 pause_after_ms 不发新请求。改 text、prompt、解析后的 voice、speech_rate、字幕开关等 body 内容会改变所有 take 指纹，需重新核对调用与费用。
5. 调用前落盘 uncertain，异常不自动重发；先核对供应商调用记录、费用与授权，再决定 --retry-uncertain。全部已完成 WAV/字幕缓存先预检，再发任何新请求；完成缓存损坏不是静默重收费的理由。

从 v0.4.1 起，模板移除音频引用标记，旧 perform 请求的 body 与指纹会变化，不能复用旧模板的缓存；重新生成前须核对费用与授权。旧文件保留，普通 TTS 指纹与缓存不受影响。

只有用户已授权且了解尚未验收的听感与音色能力风险，才执行以下**可能收费**流程（不会因为文档示例自动授权）：

```sh
# skill 目录；PLAN 指向用户作品或仓库 examples/perform/plan.json
uv run scripts/tts.py preview --plan "$PLAN" --out 阅读稿
uv run scripts/tts.py render --plan "$PLAN" --out 音频 --dry-run
# 仅在用户授权后，先局部试听 perform；此命令可能收费
uv run scripts/tts.py render --plan "$PLAN" --out 音频 --only-mode perform
# 试听后编辑 selected_take；同目录完整 render 可能需生成未缓存的 TTS
uv run scripts/tts.py render --plan "$PLAN" --out 音频
```

`--only-mode {tts,perform}` 只发送指定模式的新请求；被跳过片段若有已完成有效缓存，可以复用它完成全片。**任一跳过片段缺缓存时，不生成 final.wav、timeline.json、final.srt，只交付片段与 take 文件，并在结果说明缺失片段。** 这种不完整渲染会移除该输出目录由脚本管理的旧 final.wav / timeline.json / final.srt，保留已完成片段缓存，避免误交旧成品；完整 render 与首次同角色 A/B 短样仍可能收费，先核对授权范围。

按提供的 API 文档，响应为单个 JSON，audio 是 base64，url 短期有效（文档为 2 小时）；本工具只用 audio，不另下载 url，manifest 不保存 url 本身。目标落盘为 **24 kHz、16-bit、单声道 WAV**，不重采样、不裁剪静音、不做自动响度归一。24 kHz / 位深须校验；返回双声道时逐帧平均下混并记 downmixed=true，其他声道数拒绝。获授权 S_ 样本实际返回双声道，下混结果已核对；不能将一次观察写成接口保证单声道或保证所有音色均相同。

subtitle.sentences 的 start_time / end_time 按提供文档是整数毫秒，转换为现有 words 的片段秒时间，再按实际 PCM 长度加全片偏移导出字幕；本次 S_ 样本的返回结构、毫秒转秒与偏移已核对，不代表所有后续响应或精确口型已验收。字幕不可用时保留音频并标 invalid_subtitles / not_returned，不猜时间或自动重试。timeline 增加 mode、take、take_selection、text_match 与 rms_dbfs（观察音量、不修改音频；数字静音记 null，避免非标准 JSON 的 -Infinity）；manifest 记录 duration、original_duration（计费秒数）、耗时与 logid。

字幕启用时，返回字幕与提交文字作忽略标点的 lexical_text 比较：不一致标 text_match=false，并在结果列 text_mismatch，不报错或重生成；关闭字幕为 null。笑声文字化、加词、漏词均需听审。**text_match=true、timestamps=true、结构检查通过都不证明发音准确、演得好、干声合格或音色一致。**

### dry-run 与费用

render --dry-run 不读密钥、不联网合成，只写本地审阅文件。requests.json 中 TTS 与 perform 请求按片段分别列出，perform.text_prompt 保留完整原样；routes.json 增加 mode、perform 的 model 与 takes。即使 --only-mode 筛选调用范围，requests.json / routes.json 仍保留全计划以便审阅；tts / perform 分类统计只计算符合筛选的片段。下面是仓库示例的离线输出节选（无 only-mode，不是真实合成日志）：

```json
{
  "dry_run": true,
  "tts": {"clips": 1, "characters": 11},
  "perform": {
    "clips": 1,
    "takes": 3,
    "calls": 3,
    "characters": 22,
    "estimated_seconds": 25.8
  },
  "perform_cost_note": "按生成时长计费，约 1 元/分钟，以控制台为准",
  "estimate_note": "秒数仅为提交文本字数 × 0.3 + 2 的每 take 粗估；calls 为不考虑缓存的调用上限"
}
```

- clips 是符合 --only-mode 范围的该模式片段数（未指定时为全部）；characters 是实际提交台词的字符数，包含标点，不重复乘 takes，也不计导演 prompt。perform.takes 为该模式各片段 takes 的总和。
- **calls 是所选模式范围内的调用次数上界，不估计缓存命中，不是实际待收费调用数**；已经生成的相同 take 可能零调用复用，改 selected_take 也不会重发。dry-run 不作缓存费用承诺。
- estimated_seconds 粗估所有 perform takes 合计：每段 `(提交文本字符数 × 0.3 + 2) × takes` 后求和。示例 `(22 × 0.3 + 2) × 3 = 25.8 秒`；非返回时长、非报价，副语言或静音会改变时长。
- 费用按真实 original_duration，而不是倍速后的 duration。约 **1 元/分钟**及 **60 分钟/半年试用额度**来自提供的计费资料，价格、试用资格/余量、有效期与开通条件均以当前控制台为准；不能保证免费或低于某个金额。多 take 都计费，不用缓存上界估算保证最终账单。

### 官方依据与试听验证

音频生成 HTTP 官方页面正文已于 2026-10-12 在线复核；其余链接是提供资料中的出处，不冒充逐页实时确认或真实合成证据：

- [音频生成 HTTP API](https://docs.volcengine.com/docs/DoubaoVoice/audio-generation-http?lang=zh)：POST /tts/create、seed-audio-1.0、speaker 参考、audio_config、返回音频与字幕；接口文字 ≤3000 字符、单次最长 120 秒。
- [模型列表](https://docs.volcengine.com/docs/6561/2499930?lang=zh)、[音频生成产品简介](https://docs.volcengine.com/docs/DoubaoVoice/ProductOverview-9?lang=zh)：副语言与混音能力；新版提供的 API 说明列 18 语言，本地仅接中英。
- [计费说明](https://docs.volcengine.com/docs/6561/1359370?lang=zh)、[计费概述](https://docs.volcengine.com/docs/6561/1359369?lang=zh)：original_duration 与价格/试用条款，以账号当前控制台为准。
- [错误码](https://docs.volcengine.com/docs/6561/2534853?lang=zh)：审核、音色和时长错误；即使官方建议重试，本工具仍须人工确认 uncertain 与授权。
- [TTS HTTP](https://docs.volcengine.com/docs/DoubaoVoice/unidirectional-streaming-text-to-speech-http?lang=zh)、[音色列表](https://docs.volcengine.com/docs/DoubaoVoice/Tonelist-1?lang=zh)：普通预置 2.0 音色优先 direction；不能假定 S_ 复刻支持 TTS context_texts 情绪指令。

**试听验证：**本轮已核对一个 S_ 样本的无 code 响应兼容、24 kHz/16-bit 双声道下混、字幕结构/毫秒单位、返回时长及与 TTS 的拼接。预置 2.0 与复刻音色均使用 `references[].speaker`，使用音色 ID 时描述不写 `@音频N`；后续在授权范围内试听已有或另行获准生成的同角色 TTS / perform 样本，核对音色身份/相似度、干声/首尾静音、台词遵循与副语言动作。0 / 20000000 是兼容规则而非本轮观察到的成功码。新调用或重试仍需对应授权，不能因一次协议成功追加调用；离线验收不代替真实接口，真实返回也不代替试听。

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
- `final.srt`：用返回文字的中文句末标点及保守英文句界分句，按唯一连续字词归属取真实首尾时间，无假字幕填补停顿。跨句 token 合并字幕，不拆其时间；零时长标点允许附属于一个正时长句子，整句零时长无效。数字规范化等不能逐字对应时，只有真实文字锚点能唯一确定句界才保留分句，否则保留服务端整句时间。全无字幕时生成空文件，不捏造字幕。字词归属仅为本地内部索引，公开 JSON 格式不增加必需字段；旧 sidecar 仍可读取。

`timeline.timestamps` 只有全部片段都有字幕才为 true；混合片段仍保留可用字词，不把没有字幕的音频时长省略出偏移计算。方言 `explicit_dialect`、片段 `enable_latex_tn: true` 与字幕不兼容，自动将该请求的字幕开关设为 false（LaTeX 开关本身传入 additions）；无字幕/无效字幕正常输出 WAV 和空字词文件，并在 manifest 标记原因。不为补齐字幕自动重试或换资源。

缓存指纹包含有效字幕开关，旧无开关指纹不会直接命中。开启字幕遇到旧完成缓存缺 words 文件，或当前完成缓存丢失 words 文件时，在整个计划联网前停止，明确提示需要重新渲染。核对费用和授权后用新的输出目录；不删除旧缓存，不自动重发。旧无开关 `uncertain` 也不能被新指纹静默绕过。正常无字幕的空 words 文件可复用，避免重复收费；manifest 标记 `timestamps: true` 却变成空 sidecar 时须拒绝，不能静默改为 false。历史记录缺少字幕状态时兼容迁移为实际可用状态，不自动请求补齐。全部已完成 WAV 和字幕缓存会在任何新调用前预检；损坏 JSON、截断/无效音频、句级文字错配字词时间等都会明确拒绝，不先调用前段再发现后段损坏。已有句子直接校验，不重新构造后丢弃；缺 sentences 的旧 sidecar 只兼容生成并保存一次。字词与句子时间须能表示为有限数值、非负、有序，并在实际片段 PCM 时长内（容许 10ms 时间量化误差，不裁剪）；句级时长须为正。新响应的无效字幕降级为 `invalid_subtitles`，无效缓存则提示需要重新渲染；两者都不自动请求补齐。

WAV 预检按固定块读取全部声明 PCM 验证完整性，缓存只保留文件路径、帧数和字幕，不保留音频字节；最终 WAV 与长停顿也分块写入临时文件，完成后原子替换。未变化或仅修改停顿的缓存渲染不重写 manifest/相同字幕文件；旧元数据迁移批量保存。真实 API 调用仍在请求前即时保存 uncertain、音频和字幕文件写完后保存 complete，异常即时记录，不能为了减少写入而省略这些持久化检查点。

时间戳的对齐精度由火山接口负责。本工具保留返回字词的原始 `startTime / endTime / confidence`，只做协议/结构校验、缓存保存、本地拼接偏移与 SRT 毫秒格式转换；不修改服务端字词时间、不裁剪音频、不引入强制对齐或其他精度补偿。`timestamps: true` 只表示字幕可解析和导出，不是精确口型保证。

短句真实接口测试检查响应完整、接口字词与落盘原始值一致、时间线偏移和 SRT 导出正确；`words` 非空、时间有限且单调用于确认结构可用。最后 `endTime` 与 WAV 时长差（例如 0.3 秒参考值）、低 confidence 等另行记录为供应商对齐质量观察，不作为本工具请求/导出成功的必达条件。无字幕、服务质量观察或请求失败都应如实报告，不自动重试、修正或把观察项冒充实现错误。旧验收报告保留当时的检查结果，不改写历史以宣称通过；结构检查也不证明已试听或口型精度。

协议依据：[官方 HTTP 字幕参数与 sentence 响应](https://docs.volcengine.com/docs/DoubaoVoice/unidirectional-streaming-text-to-speech-http?lang=zh)、[完成码与流式响应示例](https://www.volcengine.com/docs/6561/1598757)。

## 已有克隆音色

本工具支持使用已训练完成且账号有权限的**声音复刻 2.0** 音色合成，不提供录音上传、音色训练、升级或旧代际接口。`S_` 前缀只用于识别克隆 ID 格式，不能据此断言训练代际；本工具默认选择 `seed-icl-2.0`，不自动试其他收费资源。下方 ID 是占位值，必须替换成自己的实际音色 ID 后使用。

```sh
uv run scripts/tts.py prepare --text-file 原稿.txt --voice S_替换成你的复刻音色ID --resource-id seed-icl-2.0 --out plan.json
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
| reference_text | 当前台词之前的真实中文或中英混读上文；省略或空字符串表示无引用 | 加“只用于理解并承接语境与情绪，不朗读”说明，合入 context_texts 首条 |
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

本工具支持中英混读：原词限 1～9 字符且不能有空格，可包含中文、英文、数字与型号标点，文本转写目标可为中英文，目标文本本地上限 500 字。括号规则仅按普通话拼音验证，不当作英语音素语法。规则原词不可重复，合并后最多 5000 条；与位置注音对同一词的相反规则会报错。补充字典不自动把多音字候选标为已校对。按实际提交文本模拟贪心最长匹配，检查全部已校对位置：转写跨到已校对位置时，本工具要求等长且替代字读音唯一、符合目标；不同长度需先明确口播改写并重新校对。只涉及数字等无位置注音的部分允许不同长度转写。

服务端字典对本请求中所有匹配原词生效，`req_params.text` 保持原稿；客户端 `spoken_alias` 按单个位置替字，实际提交文本已经变化。两者都在阅读稿中显示，不能混称。官方英文转写示例 `omg/oh my god` 已由本工具接入；配置表中的缩写与型号使用同一机制，品牌英语提示则通过指令传入。详见 [中英混读与发音表](mixed-language.md)。

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
