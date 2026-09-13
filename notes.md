# Notes: 4px 中性灰框迁移

## Inventory

### 迁移目标

- 全局 `library-form-surface` / `queue-dialog` 框架。
- EditorWorkspace 主卡片、编辑侧栏、Agent 侧栏。
- Skill、组件库、文献、灌库文件表、资源管理器侧栏。
- QueueBoard 列卡片、LibraryCard 默认封面。
- Safety、VaultFilter、VaultUnlock、Scanner URL dialog。
- Registry、Runtime APIs、Multimodal debug。
- DashboardCardFrame、TimeConsumption、LanguageTrace。
- Agent 环境卡、Child Agent conversation。
- SmartForm dialog、Feedback、Floating picker、Component upload 等保留投影的覆盖规则。
- BasicSettings 与 TopCommandBar 的中性 GitHub hover 双环。

### 明确保留

- `ActivityBar.vue` 活动栏本体 4px ring。
- `ActivityBar.vue` 附属知识子菜单活动栏 ring。
- `LibraryCard.vue` 蓝色 hover ring。
- `ui-system.css` 表单 focus ring。

### 目标样式

- 内层：`2px var(--library-form-ring)` 或原 `--workspace-panel-ring`。
- 外层：`2px var(--workspace-panel-outline)`，其中 outline 色为 35% 主题文字色。
- 两层通过 `outline-offset: 2px` 分离，避免半透明灰与外圈叠色。

## Verification

- 中性 4px 残留扫描：0。
- 预期保留 4px：表单 focus 1、LibraryCard 蓝色 hover 1、ActivityBar 2。
- 首轮样式契约：28 passed、2 failed；其中 Vault 顺序断言已修，另一个是与本次无关的既有 Agent toolbar 断言。
- 仓库级契约初版发现 raw CSS 为空，已改为真实文件系统扫描。
- 边框定向重测：3 files passed，4 tests passed。
- 仓库级真实文件扫描：1 file passed，2 tests passed。
- 待执行：边框定向重测与多尺寸页面烟测。
