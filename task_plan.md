# Task Plan: 全前端中性 4px 灰框迁移

## Goal
除左侧活动栏本体外，将所有中性 4px 灰色外框统一为已确认的 2px 原浅灰内圈 + 2px、35% 主题色外圈，并完成覆盖扫描、契约更新和多尺寸界面冒烟。

## Requirement Mapping
- “其他但凡出现了这个4px边框” → 穷举 `library-form-ring`、`workspace-panel-ring`、中性 `color-border` 4px ring 与 4px solid 灰框。
- “除了左侧活动栏” → `.activity-bar` 的 `4px var(--color-activity-bar-ring)` 保持不变。
- “全都改成这样” → 每个目标均采用同一 2+2、35% 双层结构；交互蓝色/危险色/焦点态不混入。

## Phases
- [x] Phase 1: 定义范围与成功标准
- [x] Phase 2: 穷举并分类全部 4px 外框
- [x] Phase 3: 最小化统一实现并更新契约
- [x] Phase 4: 静态残留扫描与定向测试
- [ ] Phase 5: 桌面/平板/移动实际界面冒烟
- [ ] Phase 6: 变更记录、复核与交付

## Decisions
- 保留活动栏本体原框。
- 活动栏附属知识子菜单沿用活动栏视觉，也保留原框。
- 保留蓝色选中、hover、focus、危险色等语义 4px 环。
- 使用原生 CSS，不新增依赖。
- 将 35% 主题色登记为 `--workspace-panel-outline`，避免在多组件复制颜色公式。

## Errors Encountered
- 首轮定向 Vitest：28 passed、2 failed。Vault 失败为本次正则顺序错误，已修正；Agent 工具栏结构断言失败与边框无关，保留为既有未解决项。
- 首次仓库级契约测试因 Vite raw CSS 导入为空失败；已改为 Node `globSync` + UTF-8 磁盘读取，避免空模块造成假覆盖。

## Status
**Phase 5** - 静态契约与边框用例通过，正在执行多页面多尺寸烟测。
