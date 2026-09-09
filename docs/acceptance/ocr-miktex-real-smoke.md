# PaddleOCR 与 MiKTeX 真实验收记录

## 根因与修复

- PaddleOCR：原依赖只声明基础 `paddlex`，PP-StructureV3 在创建阶段要求 `paddlex[ocr]`，因此模型下载尚未开始就失败。依赖已改为 `paddlex[ocr]==3.7.2`，并增加实际 extra 导入回归测试。
- MiKTeX：安装位于 `D:/Softwares/MiKTeX`，注册表存在 `UserInstall`，但正式进程的 PATH 不含其 `bin/x64`。发现链已加入 Windows 注册表和固定安装位置。
- 可诊断性：PaddleOCR 下载异常会把真实异常写入模型进度，供存储管理直接展示。

## 真实验收

- 受管 OCR 目录包含全部 13 个唯一组件，共 2,124,438,217 字节；marker 与模型清单一致。
- 从受管目录加载模型，对仓库现有 `tests/测试文件/表格图片.jpeg` 真实推理：1 页、1 表格、2 个结构块，正文包含结构化 HTML 表格。
- 使用现有 MiKTeX 24.1 真实编译并渲染公式与表格混合页，再执行结构化 OCR：`loaded=True`、`engine_available=True`、1 页、1 表格、1 公式、5 个结构块；公式恢复为 LaTeX，表格恢复为 HTML。
- MiKTeX 在当前 PATH 查不到任何 TeX 命令的条件下，通过安装根目录识别为 MiKTeX 24.1，默认 `pdflatex`，同时找到 `xelatex`、`lualatex` 与 `latexmk`。
- Chromium 连接真实前后端通过界面冒烟；证据见 `docs/acceptance/ocr-miktex-real-smoke.png`。
