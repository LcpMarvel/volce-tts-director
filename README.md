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
| 音色与方言 | 每个片段选择中文音色；方言使用 `explicit_dialect`，需选支持相应能力的音色 |
| 语速与停顿 | 设置语速和片段后的停顿，停顿由本地拼接处理 |
| 分角色对白 | 各角色片段分别合成，按顺序拼接 |
| 音频导出 | 输出 24 kHz、单声道、16-bit WAV，同时保存无凭据的请求与调用状态 |

引用上文是本工具的计划字段 `reference_text`，当前通过自然语言说明接入 `context_texts`。不同音色对指令、上文和纠音的遵循程度需要试听验证。

当前只做中文，接入豆包 TTS 2.0 预置音色和 v3 单向 HTTP 接口。不支持 SSML、声音复刻、英文配音、原生多人联合合成或实时播放。

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

检查覆盖中文校对、原文保留、纠音冲突、语音指令与引用上文接线、断流处理、WAV 拼接与缓存。接口依据：[火山官方 HTTP 文档](https://docs.volcengine.com/docs/DoubaoVoice/unidirectional-streaming-text-to-speech-http?lang=zh)、[语音指令与能力说明](https://docs.volcengine.com/docs/DoubaoVoice/DoubaoTextToSpeech20CapabilityIntroduction?lang=zh)。
