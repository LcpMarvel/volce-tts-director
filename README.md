# volce-tts-director · 火山中文配音导演

让你的 AI Agent 为中文稿件校对读音、安排演绎，再通过火山引擎豆包 TTS 2.0 生成配音。适用于中文旁白、故事朗读、有声内容和分角色对白。

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

当前只做中文，接入豆包 TTS 2.0 预置音色、已有的声音复刻 2.0 音色和 v3 单向 HTTP 接口。不支持录音上传/音色训练、旧代际复刻接口、SSML、英文配音、原生多人联合合成或实时播放。

## 逐字时间戳与字幕

默认请求 `req_params.audio_params.enable_subtitle: true`，适用于 TTS 2.0 / ICL 2.0（`seed-tts-2.0` / `seed-icl-2.0`）。**不使用 TTS 1.0 的 `enable_timestamp`。** 可在计划顶层或单个 clip 设置 `"enable_subtitle": false`；片段覆盖顶层，CLI `--timestamps / --no-timestamps` 覆盖两者。切换开关属于不同请求，可能需要新的收费合成。

```sh
# 只检查开启字幕的请求，不读取密钥、不联网
uv run skills/volce-tts-director/scripts/tts.py render --plan plan.json --out outputs/音频 --timestamps --dry-run

# 已授权的合成；省略 --timestamps 也默认开启
uv run skills/volce-tts-director/scripts/tts.py render --plan plan.json --out outputs/音频 --timestamps
```

生成目录包含：

- `<hash>.wav` 和同名 `<hash>.words.json`：`text`、`words` 列表及句级 `sentences`。每个词条保留服务端的 `word / startTime / endTime / confidence`（若返回）；时间是**秒，相对本次片段请求开始**。中文通常按字，标点可能附在字上，不人为拆分或估算时间。服务端字幕可能体现可听别名或数字转写，不保证与原稿逐字相同。
- `timeline.json`：`clips[].offset` 为片段在 `final.wav` 中的秒偏移，另含音频时长、`pause_after_ms`、文件路径与字幕状态；顶层 `words / sentences` 已换算到**全片秒时间**并附 `clip` ID。偏移按真实 PCM 采样数累计，包含本地停顿；延续原有行为，最后片段的段后停顿也计入最终时长。
- `final.srt`：根据返回字幕文字按中文句末标点分句，以所属字词的真实首尾时间生成字幕，不覆盖段间停顿。一个 timed token 跨句时合并字幕，不拆分其时间；零时长标点只归属一个正时长句子。数字规范化等无法逐字匹配时，仅在文字锚点可唯一确定句界时保留分句，否则保留该字幕帧的整句与首尾时间，不猜测内部时间。
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
- [SKILL.md](skills/volce-tts-director/SKILL.md)：Agent 的完整工作流程。
- [运行与计划格式](skills/volce-tts-director/references/usage.md)：字段、纠音投递方式、方言和请求细节。

示例是校对与接线材料，不代表已验证所有音色的发音效果。CLI 安装仅包含 `skills/volce-tts-director/` 下的文件；`examples/` 与开发测试保留在仓库，`outputs/` 为本地生成目录，不纳入 Git。

在仓库根目录运行离线验收，不调用 TTS：

```sh
uv run --with pypinyin==0.55.0 python tests/selfcheck.py
```

检查覆盖中文校对、原文保留、纠音冲突、语音指令与引用上文接线、断流处理、WAV 拼接与缓存，以及字幕同帧/晚到、停顿偏移合并、句级 SRT、字幕缓存指纹、缺文件阻断、降级与调试脱敏。真实接口测试须按授权执行，核对响应完整、返回字词与落盘原始值一致，以及时间线和 SRT 导出正确；离线测试不替代真实接口证据。末字结束与 WAV 时长差（例如 0.3 秒参考值）只作为供应商对齐质量观察，记录后不自动校正或重试，不作为本工具导出成功与否的判据。接口依据：[火山官方 HTTP 文档](https://docs.volcengine.com/docs/DoubaoVoice/unidirectional-streaming-text-to-speech-http?lang=zh)、[语音指令与能力说明](https://docs.volcengine.com/docs/DoubaoVoice/DoubaoTextToSpeech20CapabilityIntroduction?lang=zh)。
