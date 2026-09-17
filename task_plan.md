# Task Plan: Agent 流式文字左到右渐显

## Goal
让 Agent 页面新增的每个可见词元在任何模型输出速度下都从左到右、由浅到深平滑显现，同时保持 Markdown 正确、旧内容稳定和减少动态效果兼容。

## User Requirement Traceability
- [x] “修复” → 先建立当前无动画的失败测试，再修复共享流式 Markdown 渲染边界。
- [x] “有这样的动效” → 新增词元具有可观测的 opacity 入场动画，已显示词元不重播。
- [ ] “渐变应该从左到右” → 同批新增词元按文本顺序获得递增延迟，浏览器中验证左侧词元先完成、右侧后完成。

## Phases
- [x] Phase 1: 读取项目、调试、动画、设计与最小实现规范
- [x] Phase 2: 调查现有 Markdown 流式 DOM、测试和调用边界
- [x] Phase 3: 先写失败测试覆盖动画、方向、旧内容稳定与最终态
- [x] Phase 4: 实施最小根因修复
- [ ] Phase 5: 串行单测、类型检查和真实界面慢流/突发流验收
- [ ] Phase 6: 动画复审、变更记录、临时文件清理与交付

## Key Questions
1. 如何在不破坏 Markdown 元素、链接、代码块和引用锚点的前提下标记新增文本？
2. 如何让高速 burst 仍能呈现左到右次序，而不是同帧全部出现？
3. 最终全量重解析时如何避免已经显示的正文再次闪烁？

## Decisions Made
- 不引入第三方动画库；优先使用原生 DOM、CSS animation/WAAPI 和现有组件。
- 只动画 opacity，避免文字位移、布局抖动和额外重排。
- 减少动态效果时保留即时可读性，不排队拖慢内容。

## Errors Encountered
- 全量 `vue-tsc --build` 失败于大量既有类型错误，并额外指出本次 `Intl.Segmenter` 缺少项目 lib 声明；本次错误通过本地结构类型与逐字符 fallback 修复，不扩大修改全局 tsconfig。
- UI 冒烟默认端口 5173 已被未知现有进程占用；未终止该进程，专项 Vite 改用 5174 并在验收后自行关闭。

## Status
**Currently in Phase 5** - 运行真实 Agent 页面突发流验收并检查计算后的动画时序。
