# Notes: Agent 流式词元渐显

## Existing Evidence
- `MarkdownContent.vue` 的流式路径直接插入解析后的 DocumentFragment，没有新增词元动画。
- 活动尾部每次更新都会删除并重建，无法天然识别刚出现的单词。
- `chat.ts` 使用 `requestAnimationFrame` 合并同帧 delta；高速模型会扩大单次可见文本批次。

## Acceptance Evidence
- 修复前 `MarkdownContent.spec.ts` 新用例稳定失败：期望 `left`、`middle` 两个 `.stream-reveal-word`，实际为零。
- 单文件 Vitest 启动耗时 76.63 秒，主要为完整依赖导入与 jsdom 环境初始化；实际测试仅 230ms，不是测试死锁。
- 实现后组件单测 15/15 通过；覆盖首次词元 0→90ms 左到右延迟、新增后旧词元不重播、最终归一化等待动画完成。
- 第二次全量类型检查不再包含 `streamingTextReveal.ts` 或 `MarkdownContent.vue` 错误；命令仍被仓库既有 ImagePreviewer、SmartForms、CarouselBlock 等错误阻断。
