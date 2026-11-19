# 就医助手 · DeepSeek Harness Agent Skill

在 DeepSeek Harness 中上传材料，使用 `elder-health-cards` Skill 识别和核对体检报告、药品说明书和个人用药资料，生成大字图。Agent 根据材料给出可编辑的提醒时间草案，经用户确认且个人安排明确后，在 Harness 里创建定时任务。

## 安装和运行

需要 Node.js 24.9 或以上，以及 Python 3、Pillow、Tesseract（简体中文和英文语言包）和可用的中文字体。Ubuntu / WSL 的示例安装命令如下。

```bash
sudo apt-get install python3 python3-venv tesseract-ocr tesseract-ocr-chi-sim tesseract-ocr-eng fonts-noto-cjk
python3 -m venv .venv
source .venv/bin/activate
python -m pip install Pillow
npm install --prefix "$HOME/.local/share/elder-dsh" @deepseek-ai/dsh@0.2.2-rc.1 --no-audit --no-fund
bash start-harness.sh
```

在浏览器打开终端打印的本地链接，在 Harness「设置 → 模型」配置能调用工具的模型。选择当前仓库作为工作区，上传材料，或者先用内置虚构数据走演示流程。

> 请用 elder-health-cards Skill 和附带的虚构数据生成大字卡。

Skill 代码在 [SKILL.md](.dsh/skills/elder-health-cards/SKILL.md)。OCR、排版、语音和提醒的说明见 [工具流程](.dsh/skills/elder-health-cards/references/harness-tools.md)。云语音可选，密钥由用户在运行环境配置。定时任务到点投递到 Harness 会话。

也可以在现有 Harness 工作区的 `.dsh/skills/` 下安装整个 `elder-health-cards` 目录。平台运行包使用 [DeepSeek Harness 官方发行版](https://github.com/deepseek-ai/deepseek-harness)。

## 定时语音自动播放

使用 `bash start-harness.sh` 启动 Web，启动器会加载宿主播放插件。已经启动的实例需要重启一次才能加载该插件。语音合成沿用现有千问 API，在与启动器相同的终端配置 `CARE_QWEN_TTS_KEY`（也接受 `DASHSCOPE_API_KEY`）：

```bash
read -rsp '千问 API Key: ' CARE_QWEN_TTS_KEY
printf '\n'
export CARE_QWEN_TTS_KEY
bash start-harness.sh
```

同意发送已核对的提醒文稿后，Skill 会提前合成 WAV、保存到 `outputs/harness/reminder-audio/` 并把标识写进任务。到点由 Harness 运行机播放缓存音频，浏览器可以关闭。WSL 使用 Windows 默认音频设备；原生 Linux 需要 `paplay` 或 `aplay` 及可用的音频会话。到点时运行机须在线、未睡眠且 Harness 正在运行。旧任务只有重新生成音频并补上标识才会自动播放。远程使用时，响的是运行 Harness 的机器。

[切换到 Python 网页版](https://github.com/yangeer/elder-health-assistant/tree/python-web)
