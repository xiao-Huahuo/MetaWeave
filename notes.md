# Notes: Agent 流式词元渐显

## Existing Evidence
- `MarkdownContent.vue` 的流式路径直接插入解析后的 DocumentFragment，没有新增词元动画。
- 活动尾部每次更新都会删除并重建，无法天然识别刚出现的单词。
- `chat.ts` 使用 `requestAnimationFrame` 合并同帧 delta；高速模型会扩大单次可见文本批次。

## Acceptance Evidence
- 待填写。
