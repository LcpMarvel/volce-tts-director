# 火山中文配音导演

中文稿件校对与豆包 TTS 2.0 合成 skill：阅读稿显示多音字，支持发音字典、语音指令、引用上文、`section_id`、中文音色、方言与 WAV 导出。

## 用 vercel-labs/skills 安装

使用官方 [skills CLI](https://github.com/vercel-labs/skills)。在要使用此 skill 的**目标项目目录**运行：

```sh
# 查看可安装的 skill
DISABLE_TELEMETRY=1 npx skills add LcpMarvel/volce-tts-director --list

# 安装到目标项目的 Codex skills 目录
DISABLE_TELEMETRY=1 npx skills add LcpMarvel/volce-tts-director \
  --skill volce-tts-director --agent codex -y
```

Codex 项目安装位置为 `.agents/skills/volce-tts-director/`。Claude Code 使用 `--agent claude-code`；需要全局安装时另加 `--global`。`DISABLE_TELEMETRY=1` 关闭 CLI 遥测。已用 `skills@1.5.18` 验证本地发现和项目安装。

CLI 安装仅包含 `skills/volce-tts-director/` 下的文件。开发时也可将安装命令中的仓库地址替换为本地 clone 路径；请在另一个目标项目目录执行安装。

## 使用

在 Codex 中请求“使用 volce-tts-director 校对这段中文并生成阅读稿”，按需再请求试听。合成时通过运行环境提供 `VOLC_TTS_API_KEY`；密钥不放入计划或 skill 文件。

也可从源码运行（Python 3.10+，推荐 uv）：

```sh
uv run skills/volce-tts-director/scripts/tts.py prepare --text-file 原稿.txt --out plan.json
uv run skills/volce-tts-director/scripts/tts.py preview --plan plan.json --out 阅读稿
```

生成前先按语境校对计划中的读音。流程见 [SKILL.md](skills/volce-tts-director/SKILL.md)，参数与合成命令见 [使用说明](skills/volce-tts-director/references/usage.md)。开发验收：`uv run --with pypinyin==0.55.0 python tests/selfcheck.py`。

`examples/` 保存示例，`outputs/` 保存试听产物；两者不随 skill 安装。
