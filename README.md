# volce-tts-director · 火山中英配音导演

当前版本：[v0.3.0](https://github.com/LcpMarvel/volce-tts-director/releases/tag/v0.3.0) · 中英混读与可配置发音表。

让你的 AI Agent 为中文及中英混读稿件校对读音、安排演绎，再通过火山引擎豆包 TTS 2.0 生成配音。适用于中文旁白、夹英文品牌/技术词/型号的讲解、故事朗读和分角色对白。英文保留原文，不自动转成中文音译。

先看带注音的阅读稿，再听实际音频。原文、多音字读音、纠音方式和导演说明都可以查看与修改。

## 安装

使用 [vercel-labs/skills](https://github.com/vercel-labs/skills)，在准备使用 skill 的项目目录执行。

**Codex：**

```sh
npx skills add LcpMarvel/volce-tts-director --skill volce-tts-director --agent codex -y
```

**Claude Code：**

```sh
npx skills add LcpMarvel/volce-tts-director --skill volce-tts-director --agent claude-code -y
```

默认安装到当前项目：Codex 使用 `.agents/skills/`，Claude Code 使用 `.claude/skills/`。想在多个项目中使用，可以在命令末尾加 `--global`。只查看可安装内容：

```sh
npx skills add LcpMarvel/volce-tts-director --list
```

安装需要 Node.js / npx。阅读稿和音频脚本需要 Python 3.10+，推荐使用 [uv](https://docs.astral.sh/uv/)；`uv run` 会读取脚本内的依赖声明并安装 `pypinyin`。合成还需要可用的火山 TTS API Key 和对应音色权限；仅校对、预览和请求检查无需密钥。

## 开始使用

安装后，把原稿交给 Agent，并说明希望的音色和演绎。例如：

```text
使用 volce-tts-director 处理下面的中文旁白。
平实、克制，语速稍慢。先校对多音字，给我看带注音的阅读稿，暂不合成。

除了夜游的东西，什么都睡着。
华老栓忽然坐起身。
擦着火柴，点上遍身油腻的灯盏。
穿上华丽的衣服。
```

Agent 会保留原文，结合语境检查多音字、姓氏、地名、专名与轻声，在阅读稿中展示读音和处理方式。普通词由 Agent 校对；无法确定的私人姓名等会向你确认。

确认阅读稿后，可以继续说：

```text
用 Vivi 2.0 生成这段旁白的试听音频。火山 TTS 密钥已配置在运行环境里。
```

生成前会检查请求并说明调用范围。试听后可以要求“把华老栓的姓氏改为第四声”“这句更克制一些”或“句间停顿再长一点”。在同一输出目录中，相同请求复用已完成的音频；只改停顿时重新拼接。

合成脚本通过运行环境读取 `VOLC_TTS_API_KEY`。请在启动 Agent 的环境中配置它，密钥不写入稿件、计划或仓库。默认音色 ID 为 `zh_female_vv_uranus_bigtts`，可按角色修改；实际可用音色以账号权限和[官方音色列表](https://docs.volcengine.com/docs/DoubaoVoice/Tonelist-1?lang=zh)为准。

### 使用已有克隆音色

已训练完成且账号有合成权限的声音复刻 2.0 音色，可以直接指定 ID：

```text
用克隆音色 S_xWSg2NNT1 生成一段中文试听，先校对并检查请求。
```

脚本对 `zh_` 预置音色使用 `seed-tts-2.0`，对 `S_` 克隆音色默认选择 `seed-icl-2.0`。**`S_` 前缀不代表训练代际**：本工具只接复刻 2.0，不自动尝试旧资源、升级或训练音色。指令、方言和纠音能力以具体音色与实际试听为准；克隆草稿默认不添加语音指令。

命令行生成克隆草稿：

```sh
uv run skills/volce-tts-director/scripts/tts.py prepare --text-file 原稿.txt --voice S_xWSg2NNT1 --resource-id seed-icl-2.0 --out plan.json
```

仍需完成中文校对，再 preview、dry-run 和 render。阅读稿及 dry-run 会展示合成资源，音频目录的 `routes.json` 保存无凭据的片段路由；`requests.json` 仍只保存请求体。首次试听建议只用一个短句；调用失败不自动换资源或重试。

## 中英混读与发音表

英文品牌、技术词、缩写和数字可直接留在原稿，如 Anthropic、Claude、DeepSeek、Haiku 5.5、V4.1-Flash、OpenRouter、token、KV cache。汉字多音字仍按原文字符位置校对，不给英文逐字标普通话拼音。

[默认发音表](skills/volce-tts-director/references/pronunciations.json)随 skill 安装，可复制修改后传入 `prepare --pronunciation-table`：

```sh
uv run skills/volce-tts-director/scripts/tts.py prepare \
  --text-file examples/mixed/source.txt \
  --voice zh_male_youyoujunzi_uranus_bigtts \
  --pronunciation-table skills/volce-tts-director/references/pronunciations.json \
  --out plan.json
# 完成中文 readings 语境校对后，preview → render --dry-run → 已授权 render
```

- `words`：Anthropic → `an-THROP-ik`、Claude → `klawd`、Haiku → `HIGH-koo`，作为英语读音提示合入 `context_texts`。DeepSeek、OpenAI 等为 `null`，保留原生英语读法。**提示不是 IPA/CMU 音素控制，必须试听确认。**
- `acronyms`：KV、API、MLA、GPU、IPO 逐字母读，S-1 读 `S one`；使用官方服务端文本转写字典，例如 `API/A P I`，不改 `req_params.text`。
- `models`：显式列出要控制的型号，默认 `5.5` 和 `V4.1`；`decimal_point` 默认 `点`（Haiku 5.5 读“五点五”），也可改为英文 `point`。只编译出现的型号，不把所有日期/金额/IP 自动改读法。
- 表内容快照写入计划顶层 `pronunciation_table`；预览/合成读取同一快照。编辑外部表不会悄悄改变旧计划，修改现有作品时直接编辑计划中的表。旧计划没有该字段时不自动套用默认表。

官方音色表将 `zh_male_youyoujunzi_uranus_bigtts` 列为**悠悠君子 2.0**，中文音色也具备英语能力；继续使用 `seed-tts-2.0`。新混读计划使用官方 `explicit_language: "zh-cn"`（中文为主、支持中英混读）；纯英语片段可用 `en`，不要把中英混合段强制成 `en`。省略语言参数也有官方默认中英混读行为。无需 SSML 或额外语言检测。

发音字典是请求内全局贪心最长匹配，源词最多 9 字符且不能有空格；OpenRouter 的原生读法/英语提示不受字典源词限制。同一缩写/型号还出现在别的词内部（如 `API` 与 `OpenAPI`）时，脚本检查实际最长匹配并拒绝误改，必要时明确完整词组或自然拆段。同一个 `5.5` 既作型号又作金额时，无法用全局字典分位置处理，须移除该规则或拆段。详见[中英混读参数与表格式](skills/volce-tts-director/references/mixed-language.md)。

## 中文纠音怎么做

同一个字在同一段里可以有不同读音。上面的例子中：

| 词组 | 目标读音 | 语境 |
| --- | --- | --- |
| 睡着 | shuì zháo | 已进入睡眠状态 |
| 华老栓 | Huà lǎo shuān | “华”是姓氏，第四声 |
| 华丽 | huá lì | 形容衣服，第二声 |

因此不能把整段所有“华”都强制改成 `hua4`。需要按完整词组消歧，例如 `华老栓/(hua4)(lao3)(shuan1)` 与 `华丽/(hua2)(li4)`，并检查规则是否覆盖其他位置。

阅读稿的注音用于审稿，实际合成另选纠音方式：

| 方式 | 作用 |
| --- | --- |
| 自然读法 `native` | 保留语境校对与注音，让模型自然朗读；普通轻声优先采用 |
| 发音字典 `dictionary` | 使用 `pronunciation_dict.tone`，提交明确词组的括号拼音规则 |
| 读音指令 `instruction` | 保留原文，把目标读音写入语音指令 |
| 可听别名 `spoken_alias` | 经用户授权，在指定位置提交同音替代字并附读音指令；阅读稿展示原字与替代字 |

发音字典还支持中文文本转写，例如 `123/一百二十三`。字典按匹配词生效，可听别名按具体位置生效；脚本会检查读音冲突，避免规则覆盖已校对的位置。

自动扫描只提供候选，仍需按语境校对。**阅读稿标对、请求合法和实际读对是不同的结果，最终以试听为准。** 不把每个多音字或轻声都强制加入字典，避免破坏自然语流。

## 可以控制什么

| 能力 | 用法 |
| --- | --- |
| 多音字阅读稿 | 输出 HTML ruby 注音与 Markdown，展示校对状态、备选读音和理由 |
| 语音指令 | 用中文描述情绪、语气、重音与节奏 |
| 引用上文 | 提供真实前文，帮助承接语境；通过“只引用、不朗读”的说明合入 `context_texts`，不加入朗读正文 |
| 段落标识 | `section_id` 传入 `additions`，用于标识连续段落；不视为跨请求记忆保证 |
| 音色与方言 | 每段选择中文预置或已有克隆音色；方言使用 `explicit_dialect`，需选支持相应能力的音色 |
| 语速与停顿 | 设置语速和片段后的停顿，停顿由本地拼接处理 |
| 分角色对白 | 各角色片段分别合成，按顺序拼接 |
| 音频导出 | 输出 24 kHz、单声道、16-bit WAV，同时保存无凭据的请求与调用状态 |
| 逐字时间戳与字幕 | 每段输出 `*.words.json`，合并为含停顿偏移的 `timeline.json` 和句级 `final.srt`，用于对口型、字幕 |

引用上文是本工具的计划字段 `reference_text`，当前通过自然语言说明接入 `context_texts`。不同音色对指令、上文和纠音的遵循程度需要试听验证。

当前支持中文与英文（含中英混读），接入豆包 TTS 2.0 预置音色、已有的声音复刻 2.0 音色和 v3 单向 HTTP 接口。具体音色的英语、指令和纠音能力以官方能力表及试听为准，不仅凭 `zh_` / `S_` 前缀推断。不支持其他字母体系、录音上传/音色训练、旧代际复刻接口、SSML、原生多人联合合成或实时播放。

## 逐字时间戳与字幕

默认请求 `req_params.audio_params.enable_subtitle: true`，适用于 TTS 2.0 / ICL 2.0（`seed-tts-2.0` / `seed-icl-2.0`）。**不使用 TTS 1.0 的 `enable_timestamp`。** 可在计划顶层或单个 clip 设置 `"enable_subtitle": false`；片段覆盖顶层，CLI `--timestamps / --no-timestamps` 覆盖两者。切换开关属于不同请求，可能需要新的收费合成。

```sh
# 只检查开启字幕的请求，不读取密钥、不联网
uv run skills/volce-tts-director/scripts/tts.py render --plan plan.json --out outputs/音频 --timestamps --dry-run

# 已授权的合成；省略 --timestamps 也默认开启
uv run skills/volce-tts-director/scripts/tts.py render --plan plan.json --out outputs/音频 --timestamps
```

生成目录包含：

- `<hash>.wav` 和同名 `<hash>.words.json`：`text`、`words` 列表及句级 `sentences`。每个词条保留服务端的 `word / startTime / endTime / confidence`（若返回）；时间是**秒，相对本次片段请求开始**。中文通常按字、英文通常按词，标点可能附在词上，不人为拆分英文词或估算时间。服务端字幕可能体现字典转写、可听别名或数字规范化（如 `5.5` 返回 `five / point / five`），不保证与原稿逐字相同；原稿仍保留在 `timeline.clips[].text`。
- `timeline.json`：`clips[].offset` 为片段在 `final.wav` 中的秒偏移，另含音频时长、`pause_after_ms`、文件路径与字幕状态；顶层 `words / sentences` 已换算到**全片秒时间**并附 `clip` ID。偏移按真实 PCM 采样数累计，包含本地停顿；延续原有行为，最后片段的段后停顿也计入最终时长。
- `final.srt`：根据返回字幕文字按中文句末标点及保守英文句界分句（不拆型号/小数点和常见缩写），以所属字词的真实首尾时间生成字幕，不覆盖段间停顿。一个 timed token 跨句时合并字幕，不拆分其时间；零时长标点只归属一个正时长句子。数字规范化等无法逐字匹配时，仅在文字锚点可唯一确定句界时保留分句，否则保留该字幕帧的整句与首尾时间，不猜测内部时间。
- `manifest.json`：每个请求记录 `words_file`、`timestamps` 和 `timestamps_reason`。`timeline.timestamps` 只有全部片段有字幕才为 `true`；部分片段缺字幕时仍保留其他片段的有效字词与偏移。

**时间戳精度由火山接口负责。** 本工具保留返回字词的原始时间和置信度；只在拼接时间线中加上片段偏移、导出 SRT 时转换为毫秒格式，不校正服务端对齐、不裁剪音频，也不引入强制对齐模型。`timestamps: true` 表示字幕可解析和导出，不保证精确口型。末字与音频末尾的差距或低置信度属于服务端质量观察，不应单独判定本工具的请求、保存或导出失败。

使用 `explicit_dialect`、片段 `enable_latex_tn: true`、关闭字幕、未返回或返回无效字幕时，保留正常音频输出，记录 `timestamps: false` 与具体原因，字幕文件为显式空列表。时间戳必须可表示为有限数值、非负、有序且不超过片段音频时长（仅容许 10ms 量化误差），句级时长必须大于零；不裁剪或猜测无效时间。累计字幕中能可靠识别的字词、标点或时间修订保留最新快照，含糊的部分重叠明确降级。不要把空字幕称为对口型验收通过。

缓存指纹包含字幕开关。旧音频缺少 `words.json`，或已完成的新缓存丢失此文件时，开启字幕会**在调用前停止并明确提示需要重新渲染**；不会静默跳过、估算字幕或自动重发。核对费用与授权后使用新的输出目录重渲染。接口成功但未返回字幕的空结果也缓存，不自动反复收费尝试。manifest 标记 `timestamps: true` 却出现空 sidecar 时，视为缓存损坏并拒绝；旧记录缺少字幕状态时兼容迁移，不自动重请求。全部 WAV 以固定块读取预检完整性，最终音频流式拼接，不保留全片 PCM；未变化或仅调整停顿的缓存渲染不重写 manifest，元数据迁移批量保存，真实请求仍即时记录 uncertain/complete。

HTTP JSON 行的实际字幕字段是顶层 `sentence`，不是 WebSocket 事件封装；字幕可能晚于音频。解析必须有完成码 `20000000`，并读到响应 EOF，避免截掉晚到字幕。可用 `--debug-stream` 向 stderr 输出脱敏响应帧（音频仅显示长度，不输出密钥或请求头），用于核对协议；不触发额外请求。依据：[官方 HTTP 字幕参数与响应格式](https://docs.volcengine.com/docs/DoubaoVoice/unidirectional-streaming-text-to-speech-http?lang=zh)。

## 从命令行运行

需要直接操作计划或调试请求时，可以 clone 仓库：

```sh
git clone https://github.com/LcpMarvel/volce-tts-director.git
cd volce-tts-director

# 从 UTF-8 中文原稿生成待校对计划
uv run skills/volce-tts-director/scripts/tts.py prepare --text-file 原稿.txt --out plan.json

# 输出 HTML 与 Markdown 阅读稿
uv run skills/volce-tts-director/scripts/tts.py preview --plan plan.json --out outputs/阅读稿
```

结合语境编辑 `plan.json` 中的 `readings`，将已校对项标为 `reviewed`，再检查完整请求：

```sh
uv run skills/volce-tts-director/scripts/tts.py render --plan plan.json --out outputs/音频 --dry-run
```

`--dry-run` 不调用 TTS。真实合成需先配置 `VOLC_TTS_API_KEY`，会使用火山服务并可能产生费用：

```sh
uv run skills/volce-tts-director/scripts/tts.py render --plan plan.json --out outputs/音频
```

阅读稿位于 `outputs/阅读稿/director.html` 和 `director.md`；最终音频位于 `outputs/音频/final.wav`。连接中断时脚本保留已完成片段，将未确定结果记为 `uncertain`，不会自动重试；先核对调用结果，再决定是否重新生成。

## 示例与开发

- [中文多音字示例](examples/chinese/director.md)：银行、行长、重庆、音乐与还款。
- [华老栓示例](examples/hua-laoshuan/director.md)：保留原稿并展示按位置的可听替换。
- [语音指令与引用上文示例](examples/context/director.md)：展示正文、演绎要求和前文。
- [中英混读计划](examples/mixed/plan.json)与[原稿](examples/mixed/source.txt)：悠悠君子 2.0、英语品牌提示、型号中文“点”转写及字幕。
- [SKILL.md](skills/volce-tts-director/SKILL.md)：Agent 的完整工作流程。
- [运行与计划格式](skills/volce-tts-director/references/usage.md)：字段、纠音投递方式、方言和请求细节。

示例是校对与接线材料，不代表已验证所有音色的发音效果。CLI 安装仅包含 `skills/volce-tts-director/` 下的文件；`examples/` 与开发测试保留在仓库，`outputs/` 为本地生成目录，不纳入 Git。

在仓库根目录运行离线验收，不调用 TTS：

```sh
uv run --with pypinyin==0.55.0 python tests/selfcheck.py
```

检查覆盖中文校对、原文保留、纠音冲突、语音指令与引用上文接线、断流处理、WAV 拼接与缓存，以及字幕同帧/晚到、停顿偏移合并、句级 SRT、字幕缓存指纹、缺文件阻断、降级与调试脱敏。真实接口测试须按授权执行，核对响应完整、返回字词与落盘原始值一致，以及时间线和 SRT 导出正确；离线测试不替代真实接口证据。末字结束与 WAV 时长差（例如 0.3 秒参考值）只作为供应商对齐质量观察，记录后不自动校正或重试，不作为本工具导出成功与否的判据。接口依据：[火山官方 HTTP 文档](https://docs.volcengine.com/docs/DoubaoVoice/unidirectional-streaming-text-to-speech-http?lang=zh)、[语音指令与能力说明](https://docs.volcengine.com/docs/DoubaoVoice/DoubaoTextToSpeech20CapabilityIntroduction?lang=zh)。
