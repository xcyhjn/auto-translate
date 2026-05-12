# 输出目录约定

当前项目会按输入视频文件名自动在 `output` 根目录下创建同名子文件夹。

例如输入文件：

```text
input\example_video.mp4
```

输出结构会变成：

```text
output\example_video\
```

这个子文件夹里会包含本次处理的所有阶段文件，例如：

- `00_media_probe.json`
- `01_audio_16k.wav`
- `02_asr_raw_segments.json`
- `03_timed_source_segments.json`
- `04_source_en.srt`
- `05_translated_segments.json`
- `06_translated_zh.srt`
- `07_qa_report.json`
- `08_bilingual_zh_en.ass`
- `09_burned_bilingual_video.mp4`
- `10_manifest_bilingual.json`

这样每个视频的产物都会被隔离到自己的目录里，不会和其他视频混在一起。
