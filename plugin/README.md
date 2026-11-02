# 本地 OCR（Xiaomi-OCR-0）· DSH 插件包

把本机跑的 Xiaomi-OCR-0 注册成 Harness 的一个可开关插件。

## 它做了什么

`cordis.patch.yml` 插入一行 `@deepseek-ai/dsh-mcp-client`（id `mcp-xiaomi-ocr`），
Harness 启动时用 stdio 拉起 `../mcp_server.py`，于是模型拿到八个工具：

| 工具 | 用途 |
| --- | --- |
| `mcp__xiaomi_ocr__ocr_image` | 整页文档 → Markdown（表格 OTSL、公式 LaTeX、阅读顺序） |
| `mcp__xiaomi_ocr__ocr_text` | 截图/小票/标识牌 → 纯文本 |
| `mcp__xiaomi_ocr__kie_image` | 发票/收据/证件 → 指定字段 JSON |
| `mcp__xiaomi_ocr__vqa_image` | 就文档图提问（金额、日期、图表读数） |
| `mcp__xiaomi_ocr__ocr_pdf` | PDF 逐页解析（默认前 5 页，需要 PyMuPDF） |
| `mcp__xiaomi_ocr__ocr_batch` | 一次多图（串行 + 缓存） |
| `mcp__xiaomi_ocr__model_status` | 模型是否在显存、空闲多少秒、剩余显存 |
| `mcp__xiaomi_ocr__model_release` | 立刻释放显存（下次调用再加载） |

结果默认 compact（`detail="brief"`）、分辨率按视觉 token 预算自动选、同图同任务走磁盘缓存；
表格由 OTSL 自动转成 Markdown。模型按需加载，空闲 `XIAOMI_OCR_IDLE_UNLOAD_S`（默认 120）秒后自动卸载。

## 安装

Plugins → **Add plugin** → 粘贴本地路径：

```
F:\harness\work\somethingfun\xiaomi-ocr\plugin
```

装好后 Plugins 列表出现「本地 OCR（Xiaomi-OCR-0）」卡片，卡片和卡片里的
`mcp-xiaomi-ocr` 行都各有一个开关；关掉即不加载模型、不占显存。

## 备注

- 模型权重与 venv 都在上一级目录，本包只有几 KB，不含权重。
- 路径写死在 `cordis.patch.yml`；项目挪位置后改这里即可。
- 首次调用才加载模型（约 7 秒、1.7GB 显存），之后会话内常驻。
- 工具超时 15 分钟（默认 60 秒对整页解析不够）。
