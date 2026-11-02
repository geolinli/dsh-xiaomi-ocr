# Xiaomi-OCR-0 本地 OCR 插件 · DeepSeek Harness

**中文** | [English](README.en.md)

把小米开源的 **Xiaomi-OCR-0（0.8B）** 装成本地 MCP 工具：agent 能读截图、读 PDF、抽票据字段，**全程离线、零 API 费用**。

一条命令装好 Python 环境 + 1.7GB 权重 + Harness 配置，**模型由脚本自动下载，不需要自己找、自己放**。

---

## 快速开始（三步）

### 1. 克隆

```powershell
git clone https://github.com/geolinli/dsh-xiaomi-ocr.git
cd dsh-xiaomi-ocr
```

### 2. 安装（含模型）

```powershell
# Windows
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

```bash
# Linux / macOS
bash install.sh
```

脚本依次完成：建 `.venv` → 装依赖（约 3GB）→ **下载模型 1.7GB** → 生成插件配置。约 10–20 分钟，中断可重跑（模型支持断点续传）。

安装结束会打印类似：

```
PASTE THIS PLUGIN DIRECTORY INTO HARNESS (Plugins -> Add plugin):
    D:\tools\dsh-xiaomi-ocr\plugin
```

### 3. 在 Harness 里登记插件

1. 重启 DeepSeek Harness
2. 左侧栏点 **Plugins**
3. 点右上角 **Add plugin**（或箭头菜单里的 **Install a third-party plugin**）
4. 在包路径输入框里**粘贴上一步终端打印的路径**——注意是仓库里的 `plugin` 子目录，不是仓库根目录：

   | 系统 | 粘贴内容示例 |
   | --- | --- |
   | Windows | `D:\tools\dsh-xiaomi-ocr\plugin` |
   | Linux | `/home/you/dsh-xiaomi-ocr/plugin` |
   | macOS | `/Users/you/dsh-xiaomi-ocr/plugin` |

   这个目录里有 `package.json`（插件清单）和 `cordis.patch.yml`（安装脚本生成的配置）。
5. 点 **Install**。列表中出现「本地 OCR（Xiaomi-OCR-0）」卡片，开关默认是开的

装好后新开会话就带 8 个工具，不用每次手动启用。

> **非官方项目**：与小米、DeepSeek 无隶属或背书关系。模型权重 Apache-2.0（不随仓库分发），依赖与合规说明见 [THIRD_PARTY.md](THIRD_PARTY.md)。

---

## 为什么值得装

### 1. 图片不再进 API，成本归零
没有它，一张图要么走视觉 API（按图片 token 计费），要么 agent 根本"看不见"。装好之后：图片 → 本地 0.8B 模型 → 几百字符文本 → 进上下文。识别过程 0 元。

### 2. 0.8B 的尺寸，4GB 显存就能跑

| 场景 | 输入 | 输出 | 耗时 | 显存峰值 |
| --- | --- | --- | --- | --- |
| 手机拍的整页试卷（1280×1700） | 1221 tok | 239 tok | 40s | 1.9 GiB |
| 密集公式页（1280px） | 1232 tok | 400 tok | 77s | 1.84 GiB |
| 小票全文（932×1644） | 941 tok | 301 tok | 43s | 1.8 GiB |
| 书法短文本 | 517 tok | 24 tok | 2.5s | 1.7 GiB |

### 3. 一个模型，三种活

| 能力 | 工具 | 输出 |
| --- | --- | --- |
| 文档解析 | `ocr_image` | Markdown（表格 OTSL→Markdown、公式 LaTeX、按阅读顺序） |
| 纯文本 | `ocr_text` | 截图/招牌/小票文字 |
| 字段抽取 | `kie_image` | 指定字段 JSON |
| 看图问答 | `vqa_image` | 就金额、日期、图表读数提问 |
| PDF | `ocr_pdf` | 逐页 Markdown，默认前 5 页 |
| 批量 | `ocr_batch` | 一次多图，串行 + 缓存 |
| 运维 | `model_status` / `model_release` | 查占用 / 立即释放显存 |

### 4. 接口按 agent 的用法设计
- **分辨率自己算**：按视觉 token 预算（默认 1200）反算长边，调用方只传路径
- **输出紧凑**：默认 `brief`，限 6000 字符；超了打 `truncated` 标记，不静默截断
- **磁盘缓存**：同图同任务 0 秒命中，跨会话有效
- **表格直出 Markdown**：不用 agent 解析 OTSL 标签

### 5. 显存按任务释放

| 调用形态 | 结束动作 | 实测 |
| --- | --- | --- |
| 默认（`hold=false`） | **立刻卸载** | 1957 MiB → 141 MiB |
| 显式 `hold=true` | 保持 600s，连续调用不再付 7s 加载 | `held_seconds_left: 598.9` |
| 闲置 600s（`EXIT_IDLE_S`） | 进程退出，内存归零 | RSS → 0 |
| `model_release` | 立即 | 141 MiB |

多页作业不需要 `hold`：`ocr_batch` / `ocr_pdf` 在一次调用内处理完全部页面，返回即释放。

### 6. 不改 Harness 源码
只往 profile 里加一行 `@deepseek-ai/dsh-mcp-client` 配置，走 Harness 自带的插件系统。卸载 = 删插件。

### 7. 数据不出机器
权重、推理、缓存全在本机；`huggingface.co` 被封锁也能装（默认走 `hf-mirror.com`）。票据、证件、合同不经过任何服务器。

---

## 环境要求

| 项 | 要求 |
| --- | --- |
| Python | 3.10 – 3.13 |
| 显存 | ≥4 GB（长边 1280）；≥8 GB 可整页 2048px |
| 内存 | ≥8 GB 空闲 |
| 磁盘 | 约 5 GB（venv 3GB + 权重 1.7GB） |
| 系统 | Windows 10/11、Linux（macOS 需自行改 `--device mps`） |
| Harness | 带 `@deepseek-ai/dsh-mcp-client` 的版本 |

## 安装参数

```powershell
.\install.ps1 -Cpu                                    # 无 N 卡，装 CPU 版 torch
.\install.ps1 -ModelMirror https://huggingface.co      # 换模型源（默认 hf-mirror.com）
.\install.ps1 -SkipModel                               # 已有权重，跳过下载
.\install.ps1 -RenderOnly                              # 只重新生成插件配置
```

```bash
bash install.sh --cpu --mirror https://huggingface.co --skip-model --render-only
```

## 配置项

改 `plugin/cordis.patch.yml` 的 `env`，然后到 Plugins 里把 `mcp-xiaomi-ocr` 那一行关一下再开：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `XIAOMI_OCR_TOKEN_BUDGET` | `1200` | 视觉 token 预算，决定自动分辨率 |
| `XIAOMI_OCR_MAX_SIDE` | `1536` | 长边硬上限 |
| `XIAOMI_OCR_IDLE_UNLOAD_S` | `120` | 兜底空闲卸载 |
| `XIAOMI_OCR_HOLD_S` | `600` | `hold=true` 的保留时长 |
| `XIAOMI_OCR_SINGLE_RELEASE` | `1` | 单次调用结束立即释放 |
| `XIAOMI_OCR_EXIT_IDLE_S` | `600` | 空闲后进程退出；`0` = 常驻 |
| `XIAOMI_OCR_BRIEF_CHARS` | `6000` | brief 模式字符上限 |
| `XIAOMI_OCR_DEVICE` | `cuda` | `cuda` / `cpu` |

## 常见问题

**Q: 速度只有 4–10 tok/s？**
Windows 上没有 `causal_conv1d` / `flash-linear-attention` 内核，线性注意力走参考实现。实测热态解码约 65 tok/s、图像 prefill 约 10ms/token，瓶颈主要在"看图"。Linux + vLLM 会快一个量级。

**Q: 显存不够 / OOM？**
把 `XIAOMI_OCR_MAX_SIDE` 降到 1024，或调小 `XIAOMI_OCR_TOKEN_BUDGET`。

**Q: `huggingface.co` 连不上？**
脚本默认用 `hf-mirror.com`，也可 `-ModelMirror` 指定。

**Q: 表格输出是 `<fcel>` 标签？**
那是 OTSL。`intent="table"` / `"markdown"` 时已自动转 Markdown；`ocr_text` 是纯文本提示词，不转换。

**Q: 怎么确认走的是本地模型？**
返回结果末尾注释里有 `{"device": "cuda", "cache": "miss|hit", "seconds": ...}`；或让 agent 调 `model_status` 看 `loaded` 和 `vram`。

**Q: 怎么彻底卸载？**
Plugins 里移除卡片，再删掉仓库目录。

## 许可与合规

| 对象 | 许可 |
| --- | --- |
| 本仓库代码 | MIT（见 [LICENSE](LICENSE)） |
| Xiaomi-OCR-0 权重 | Apache-2.0（小米研究院） |
| 上游基座 Qwen3.5-0.8B-Base | Apache-2.0 |
| PDF 渲染 | pypdfium2（PDFium，Apache-2.0 / BSD-3-Clause） |

完整清单见 [THIRD_PARTY.md](THIRD_PARTY.md)。
