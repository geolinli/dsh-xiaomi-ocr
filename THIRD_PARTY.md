# 第三方组件与许可

本仓库**不包含任何模型权重**，安装脚本从公开来源按需下载。下面列出各组件及其许可，便于合规审查。

## 模型

| 组件 | 许可 | 来源 | 是否随仓库分发 |
| --- | --- | --- | --- |
| Xiaomi-OCR-0（0.8B） | **Apache-2.0** | [xiaomi-research/Xiaomi-OCR-0](https://huggingface.co/xiaomi-research/Xiaomi-OCR-0) | 否，安装时下载（约 1.7 GB） |
| Qwen3.5-0.8B-Base（上游基座） | **Apache-2.0** | [Qwen/Qwen3.5-0.8B-Base](https://huggingface.co/Qwen/Qwen3.5-0.8B-Base) | 否（已合入上面的权重） |
| PP-DocLayoutV3（可选，未集成） | **Apache-2.0** | [PaddlePaddle/PP-DocLayoutV3](https://huggingface.co/PaddlePaddle/PP-DocLayoutV3) | 否 |

Apache-2.0 允许商用与再分发，义务是：保留版权与许可声明、随分发提供许可证副本、若修改文件需注明、附带上游 NOTICE（如上游提供）。**如果你要把权重再分发出去（例如打进自己的镜像），请自行附上 Apache-2.0 全文与小米的版权声明。**

## 运行时依赖

| 包 | 许可 | 用途 |
| --- | --- | --- |
| torch / torchvision | BSD-3-Clause | 推理 |
| transformers / tokenizers / safetensors / huggingface-hub | Apache-2.0 | 模型加载 |
| accelerate | Apache-2.0 | 设备放置 |
| Pillow | HPND（MIT-CMU 系） | 图像解码 |
| numpy | BSD-3-Clause | 数值 |
| psutil | BSD-3-Clause | 进程内存诊断 |
| mcp（Python SDK） | MIT | MCP 协议 |
| **pypdfium2** | **Apache-2.0 / BSD-3-Clause**（PDFium） | PDF 渲染 |

### 关于 PDF 依赖（重要）

早期版本用 **PyMuPDF** 渲染 PDF，但它是 **AGPL-3.0**（或商业授权）。AGPL 对"通过网络提供服务"的场景有传染性要求，不适合作为默认依赖推荐给别人，因此已替换为 **pypdfium2**（PDFium，Apache-2.0/BSD-3-Clause）。

请不要在本仓库的安装流程里改回 `pymupdf`；确有需要请让使用者自行安装并自行评估许可。

## 本项目许可

本仓库代码：**MIT**（见 [LICENSE](LICENSE)）。模型权重不在此许可范围内。

## 免责声明

- 本项目是**非官方**社区工具，与小米（Xiaomi）、DeepSeek 均无隶属或背书关系。
- 模型效果数据来自小米官方模型卡的自测结果，**未经本仓库独立复现**；"Real5 排名第一"存在评测口径争议（自测 95.24 vs 公开榜 92.73），选型请以自己数据的实测为准。
- 模型输出可能包含识别错误。用于合同、票据、证件等场景时请保留人工复核。
- 识别结果与缓存（`tmp/cache/`）都留在本机，不上传；但**缓存是明文 JSON**，处理敏感文件后请自行清理该目录。
