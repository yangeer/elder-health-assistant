# 云端语音与家人音色

默认采用阿里云百炼 CosyVoice 北京地域的非实时 HTTP 接口。先用预置音色试听，满意后可改用子女本人的音色。生成时只提交确认过的语音稿，报告与处方照片无需传给语音服务。以下命令从 Skill 根目录运行。

## 预置普通话音色

在终端环境中配置北京地域的 `DASHSCOPE_WORKSPACE_ID` 和 `DASHSCOPE_API_KEY`。密钥保存在本机环境变量或密钥管理服务中。Python 3 脚本直接调用 HTTP：

```bash
python3 scripts/synthesize_cosyvoice.py "语音叮嘱稿.txt" "用药提醒.wav"
```

带有 FFmpeg 的环境可以直接把输出文件名改为 `用药提醒.mp3`。脚本会在输出前检查原始音频的实际时长，超过 60 秒时提示精简文稿。

## 同一入口创建并使用家人音色

服务维护者预先配置百炼北京地域的凭据。使用者在当前 Skill 对话提交录音附件或提供本地路径，并确认录音人同意上传到阿里云百炼用于家庭用药提醒。宿主须能访问录音文件并运行 Python。Agent 运行下列命令，使用者无需访问百炼网页或手工填写音色 ID。

建议由子女本人在安静环境录制 10～20 秒普通话。可用 WAV（16 位）、MP3 或手机常见的 M4A。采样率至少 16 kHz，最长 60 秒，文件不超过 10 MB。录音只读普通文字，避开个人病历、姓名和药量。

首次创建并合成：

```bash
python3 scripts/synthesize_cosyvoice.py "语音叮嘱稿.txt" "家人音色提醒.wav" \
  --sample "子女录音.m4a" --voice-profile "家人音色.json" --speaker-consent
```

脚本通过 HTTPS 提交录音并把返回的音色 ID、模型与业务空间存入本地档案。录音无需公开托管。审核通过后会继续合成。审核较慢时，先保留档案，稍后执行下列同一命令即可继续查询并生成。每次生成新文稿也用该命令：

```bash
python3 scripts/synthesize_cosyvoice.py "语音叮嘱稿.txt" "家人音色提醒.wav" \
  --voice-profile "家人音色.json"
```

有现成音色的人也可以使用 `--model` 和 `--voice`。若档案提示创建结果待核对，请先核对服务端是否已建成，避免重复创建音色。录音人撤回同意后停止使用该档案，并请维护者根据百炼指引删除音色。

脚本在开头朗读合成语音提示。正文用家里日常的称呼和短句。语速默认 0.92，可用 `--rate` 调整。请子女试听并核对药名、剂量单位和时间，医嘱变化后更新卡片和音频。

[百炼音色创建接口和审核状态](https://help.aliyun.com/zh/model-studio/voice-clone-design-http-api) · [录音要求](https://help.aliyun.com/zh/model-studio/voice-cloning-user-guide) · [CosyVoice 合成接口](https://help.aliyun.com/zh/model-studio/cosyvoice-tts-http-api)
