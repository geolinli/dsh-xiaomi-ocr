# Xiaomi-OCR-0 本地 OCR 插件 for DeepSeek Harness

把小米开源的 **Xiaomi-OCR-0（0.8B）** 装成本地 MCP 工具，让 Harness 的 agent 能读图、读 PDF、抽票据字段——**全程离线、零 API 费用**。

一条命令装好：Python 环境 + 1.7GB 权重 + Harness 配置。装完在 Plugins 页面里开关。

```powershell
# Windows
git clone https://github.com/geolinli/dsh-xiaomi-ocr.git
cd dsh-xiaomi-ocr
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

```bash
# Linux / macOS
git clone https://github.com/geolinli/dsh-xiaomi-ocr.git
cd dsh-xiaomi-ocr
bash install.sh
```

装完重启 Harness → 左侧 **Plugins → Add plugin** → 填终端打印的那个目录路径 → 出现「本地 OCR（Xiaomi-OCR-0）」卡片，默认开启。

> **非官方项目**：与小米、DeepSeek 无隶属或背书关系。模型权重 Apache-2.0（不随本仓库分发，安装时下载），依赖清单与合规说明见 [THIRD_PARTY.md](THIRD_PARTY.md)。

---

## 为什么值得装

### 1. 图片不再进 API，成本归零

没有这个插件时，一张图要么走视觉 API（图片 token 按量计费），要么 agent 根本"看不见"。装好之后：图片 → 本地 0.8B 模型 → 几百字符文本 → 进上下文。**识别过程 0 元，上下文只花几百 token**。

### 2. 0.8B 的尺寸，4GB 显存就能跑

实测（RTX 3050 Laptop 4GB / fp16 / Windows）：

| 场景 | 输入 | 输出 | 耗时 | 显存峰值 |
| --- | --- | --- | --- | --- |
| 手机拍的整页试卷（1280×1700） | 1221 tok | 239 tok | 40s | 1.9 GiB |
| 密集公式页（1280px） | 1232 tok | 400 tok | 77s | 1.84 GiB |
| 小票全文（932×1644） | 941 tok | 301 tok | 43s | 1.8 GiB |
| 书法短文本 | 517 tok | 24 tok | 2.5s | 1.7 GiB |

模型只有 **1.63 GiB**（bf16 单文件），8GB 显存可以开并发，4GB 卡压到 1280px 长边就够用。

### 3. 一个模型，三种活

| 能力 | 工具 | 输出 |
| --- | --- | --- |
| 文档解析 | `ocr_image` | Markdown（表格 OTSL→Markdown、公式 LaTeX、按阅读顺序） |
| 纯文本 | `ocr_text` | 截图/招牌/小票文字 |
| 字段抽取 | `kie_image` | 指定字段的 JSON |
| 看图问答 | `vqa_image` | 就金额、日期、图表读数提问 |
| PDF | `ocr_pdf` | 逐页 Markdown，默认只取前 5 页 |

整页试卷连"★考生注意事项★"里的 `(书)`、`2B` 空格都逐字还原；票据字段 `date/seller_gst_id/total_tax` 全对；公式输出 `\mathbf{P}_i^j = \prod...\tag{5}` 这种带编号的 LaTeX。

### 4. 接口是照着 agent 的用法设计的

不是"给人点的网页"，是给 agent 调的工具，所以默认值都在省上下文和省时间：

- **分辨率自己算**：按视觉 token 预算（默认 1200）反算长边，调用方只传路径，不用调 `max_side`
- **输出紧凑**：默认 `brief`，压空行、限 6000 字符；超了打 `truncated` 标记，**不静默截断**
- **磁盘缓存**：同图同任务命中 0 秒，跨会话有效（按文件 sha256 索引）
- **批量**：`ocr_batch` 一次多图，多页只付一次模型加载
- **表格直出 Markdown**：不用 agent 自己解析 OTSL 标签

### 5. 显存按任务释放，不是死等超时

| 调用形态 | 结束动作 | 实测 |
| --- | --- | --- |
| 单图（默认 `hold=false`） | **立刻卸载** | 1957 MiB → 139 MiB |
| 批量 / PDF（默认 `hold=true`） | 保持 600s | `held_seconds_left: 598.9` |
| 空闲 600s（`EXIT_IDLE_S`） | 进程退出，内存归零 | 连 3.6GB 常驻内存一起还 |
| 显式 `model_release` | 立即 | 139 MiB |

`model_status` 会直接告诉你原因：`retention: "released (single-shot)"` / `"held 600s after last call"`。

### 6. 不改 Harness 源码

走的是 Harness 自带的 MCP 客户端插件，只往 profile 里加**一行** `@deepseek-ai/dsh-mcp-client` 配置。卸载 = 删掉插件包，Harness 本身零改动。

### 7. 数据不出机器

模型权重、推理、缓存全在本机；hosts 里可以把 `huggingface.co` 指到 127.0.0.1 也能跑（安装脚本支持 `-ModelMirror`）。票据、证件、合同这类材料不需要上传任何地方。

---

## 工作原理

```
图片/PDF
   │
   ├─ mcp_server.py (本地 Python, stdio)
   │     ├─ 自动分辨率（视觉 token 预算）
   │     ├─ 磁盘缓存（sha256）
   │     ├─ OTSL → Markdown
   │     └─ 显存：懒加载 / 按任务释放
   │            │
   │            └── transformers + Xiaomi-OCR-0 (0.8B, bf16/fp16)
   │
   └─ @deepseek-ai/dsh-mcp-client (Harness 内置)
         └─ 工具：mcp__xiaomi_ocr__ocr_image / ocr_text / kie_image /
                  vqa_image / ocr_batch / ocr_pdf / model_status / model_release
```

## 环境要求

| 项 | 要求 |
| --- | --- |
| Python | 3.10 – 3.13 |
| 显存 | ≥4 GB（长边 1280）；≥8 GB 可整页 2048px |
| 内存 | ≥8 GB 空闲（模型 1.7GB + torch 运行时） |
| 磁盘 | 约 5 GB（venv 3GB + 权重 1.7GB） |
| 系统 | Windows 10/11、Linux；macOS 需自行改 `--device mps` |
| Harness | 带 `@deepseek-ai/dsh-mcp-client` 的桌面版 / Web 版 |

## 安装细节

`install.ps1` / `install.sh` 会做四件事：

1. 建 `.venv`（Python 3.10+），装 `torch 2.14 + transformers 5.17 + mcp`
   - 默认装 CUDA 版（Windows 走 `download.pytorch.org/whl/cu130`，因为 PyPI 上的 Windows 轮子是 CPU-only）
   - `-Cpu` / `--cpu` 装纯 CPU 版
2. 从 HF 镜像拉权重到 `model/`（约 1.7GB，可断点续传）
3. 生成 `plugin/cordis.patch.yml`，把绝对路径写进去
4. 打印下一步：在 Harness 的 Plugins 页面填哪个路径

```powershell
.\install.ps1 -Cpu                              # 无 N 卡
.\install.ps1 -ModelMirror https://hf-mirror.com # 换镜像（默认就是它）
.\install.ps1 -SkipModel                        # 已有权重，跳过下载
```

## 配置项

都在 `plugin/cordis.patch.yml` 的 `env` 里，改完把插件行关一下再开：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `XIAOMI_OCR_TOKEN_BUDGET` | `1200` | 视觉 token 预算，决定自动分辨率 |
| `XIAOMI_OCR_MAX_SIDE` | `1536` | 长边硬上限 |
| `XIAOMI_OCR_IDLE_UNLOAD_S` | `120` | 兜底空闲卸载 |
| `XIAOMI_OCR_HOLD_S` | `600` | `hold=true` 的保留时长 |
| `XIAOMI_OCR_SINGLE_RELEASE` | `1` | 单图结束立即释放 |
| `XIAOMI_OCR_EXIT_IDLE_S` | `600` | 空闲后进程退出；`0` = 常驻 |
| `XIAOMI_OCR_BRIEF_CHARS` | `6000` | brief 模式字符上限 |
| `XIAOMI_OCR_DEVICE` | `cuda` | `cuda` / `cpu` |

## 常见问题

**Q: 速度只有 4–10 tok/s？**
Windows 上没有 `causal_conv1d` / `flash-linear-attention` 内核，18 层线性注意力走 PyTorch 参考实现。这是算子问题不是模型上限，Linux + vLLM/SGLang 快一个量级。离线批处理够用。

**Q: 显存不够 / OOM？**
把 `XIAOMI_OCR_MAX_SIDE` 降到 1024，或调小 `XIAOMI_OCR_TOKEN_BUDGET`。小票/证件 1024 足够。

**Q: `huggingface.co` 连不上？**
安装脚本默认用 `hf-mirror.com`，也可以 `-ModelMirror` 指定其它镜像。

**Q: 表格输出是 `<fcel>` 这种标签？**
那是 OTSL。本插件在 `intent="table"/"markdown"` 时已自动转成 Markdown 表格；`ocr_text` 走纯文本提示词，不会转换。

**Q: 怎么彻底卸载？**
Plugins 里移除卡片，然后删掉这个目录、以及 profile 里 `cordis.patch.yml` 的相关行。

## 许可与合规

| 对象 | 许可 |
| --- | --- |
| 本仓库代码 | **MIT**（见 [LICENSE](LICENSE)） |
| Xiaomi-OCR-0 权重 | **Apache-2.0**（小米研究院，安装时从 HF/镜像下载） |
| 上游基座 Qwen3.5-0.8B-Base | **Apache-2.0** |
| PDF 渲染 | **pypdfium2**（PDFium，Apache-2.0/BSD-3-Clause） |

几个刻意的选择：

- **不打包权重**：仓库里没有 1.7GB 权重，安装器按需下载。这样既避免再分发的声明义务，也让权重始终跟随上游更新。
- **不用 PyMuPDF**：它虽然好用，但许可是 **AGPL-3.0**，对"通过网络提供服务"有传染性要求，不适合作为默认依赖推荐给他人。已换成 pypdfium2。
- **不复制第三方代码**：所有依赖都通过 pip 安装，仓库只含本项目自己的 MIT 代码。

使用前请注意：

- 模型成绩来自小米官方模型卡的自测，**未经独立复现**；Real5 的"第一"存在评测口径争议，选型请用自己数据实测。
- 模型会输出识别错误，合同/票据/证件场景请保留人工复核。
- 缓存（`tmp/cache/`）是**明文 JSON** 且留在本机，处理敏感材料后请清理该目录。

完整依赖与许可清单见 [THIRD_PARTY.md](THIRD_PARTY.md)。

## English quick start

```powershell
git clone https://github.com/geolinli/dsh-xiaomi-ocr.git
cd dsh-xiaomi-ocr
powershell -ExecutionPolicy Bypass -File .\install.ps1      # add -Cpu for CPU-only
```

Then restart Harness → **Plugins → Add plugin** → paste the printed plugin directory. Tools appear as `mcp__xiaomi_ocr__ocr_image`, `__ocr_text`, `__kie_image`, `__vqa_image`, `__ocr_batch`, `__ocr_pdf`.

Fully offline. Xiaomi-OCR-0 is a 0.8B document model: page → Markdown (tables/formulas), receipt → JSON, document Q&A. Runs on a 4GB GPU with `XIAOMI_OCR_MAX_SIDE=1280`.
