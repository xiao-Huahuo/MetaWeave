# MinerU 精准 API 双链路验收

## TODO 逐句对应

| 用户要求 | 实现证据 | 验收证据 |
|---|---|---|
| 扫描器与灌库接入 MinerU 精准 API，并强调双链路 | `document_parsing/mineru.py`、`frontmatter_bootstrap.py`、`knowledge_library/ingestion.py`、`scanner/service.py`；README 与 `docs/WORKFLOW.md` | `test_mineru_document_parsing.py`、`test_scanner_service.py` |
| MinerU 优先，本地保留，不影响切片/预览 | 只在 frontmatter 的多模态清洗分支选择解析器；`KnowledgeIngestionService`、预览 API 未改 | 多模态/结构化 OCR 43 项及入库任务 17 项通过 |
| 不自动加载/下载本地 OCR；实际使用才同步准备 | `ImageOcrService.ensure_ready()`；启动模型管理跳过 PaddleOCR | `test_model_management_service.py` 与扫描器服务回归通过 |
| 适配限流、并发、文件上限、页数、模型 | `AgentConfig.VlmConfig`、用户 VLM 配置、分钟滑窗、跨进程有界租约、200 MB/600 页预检 | MinerU 客户端与设置服务测试通过 |
| 新增 OCR/VLM 设置并迁移基础 OCR | `VlmSettingsSection.vue`、`SettingsSidebar.vue`、迁移 `20260911_0016` | Vitest 与 `mineru-vlm-settings-*.png` |
| 扫描器临时联网、断网关闭/回退、进度按方式变化 | `ScannerParsingSettingsMenu.vue`、`ScannerUploadPanel.vue`、任务解析器快照 | 断网单测、Scanner Vitest、`mineru-scanner-menu-1024.png` |
| MinerU Markdown 默认显示且适配矩形框 | ZIP Markdown/资源读取、0–1000 bbox 映射、复用 `OcrBlockOverlay` | `mineru-result-blocks-1024.png`，左右块均由 Playwright 断言可见 |
| 扫描队列复用设置按钮并影响后续任务 | 同一 `ScannerParsingSettingsMenu` 挂到 `QueueBoardShell` toolbar，任务提交固化选项 | Batch Scanner Vitest、`mineru-queue-menu-1024.png` |
| 入库队列与 Debug 适配联网 | 入库队列对 `vlm_*` 阶段显示不定进度；Debug 按解析器缓存合同重建 | IngestionProgress Vitest、Debug 后端回归 |

## 实际命令与结果

- `python -m pytest -q tests/test_mineru_document_parsing.py tests/test_multimodal_cleaner.py tests/test_structured_ocr_pipeline.py`：43 passed。
- `python -m pytest -q tests/test_scanner_service.py`：10 passed。
- `python -m pytest -q tests/test_settings_llm_config.py`：16 passed。
- 设置/管理 API、gRPC、入库任务、Debug、迁移等分批回归均通过。
- MinerU 相关前端定向 Vitest 分批运行通过；最近完整相关批次 32 passed。
- `npm run build-only`：Vite production build passed。
- `npx playwright test mineru-vlm.spec.ts --project=chromium --workers=1 --max-failures=1 --retries=0`：1 passed。
- Vite 5173 开发代理真实请求 `/settings/vlm/config` 返回 200 及 200 MB、600 页、`vlm` 等后端默认值。

## 视觉复审

- 1024/768/480 均无横向溢出；移动端设置导航会自动把当前 OCR/VLM 页签完整滚入视口。
- 深色、浅色和 `prefers-reduced-motion: reduce` 已覆盖。
- MinerU 结果截图确认原件矩形框与右侧 Markdown 块同时显示，沿用既有双栏联动样式。

## 未完成/外部条件

- 当前主机没有配置 `MINERU_API_TOKEN`，因此未向 MinerU 上传真实用户文件。精准 API 成功路径使用官方请求/响应合同、ZIP 和 `content_list.json` 模拟完成；用户在 OCR/VLM 设置页填写自己的 Token 后才能执行真实外部成功路径。
- 仓库全量 `vue-tsc --build` 仍被任务前已存在的无关类型错误阻断；本次相关 Vitest 与 Vite 生产构建通过，未修改那些无关文件。
