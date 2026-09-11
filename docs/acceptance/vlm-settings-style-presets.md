# OCR/VLM 设置样式与预设对应

| 用户要求 | 实现位置 |
|---|---|
| VLM 输入动效、文字格式和左侧留白与 LLM 一致 | `SettingsView.vue` 的 `.settings-model-form` 共享规则；`VlmSettingsSection.vue` 使用同一 `model-block`、`key-row`、`capacity-row` 与按钮类 |
| 学习 LLM 查看/编辑交互 | `VlmSettingsSection.vue` 新增 effective/draft、编辑、保存、取消、检查连接状态 |
| 保存和加载模型配置 | `UserVlmConfigPreset`、迁移 `20260911_0017`、SettingsService、REST/gRPC、`settings.ts` 与 VLM 预设操作 |
| LLM 已保存块向图书馆条形模式对齐 | `SavedModelConfigRow.vue` 复用 LibraryBar 的水平视觉锚点、主信息与操作轨道结构 |
| LLM/VLM 协调 | 两页共同使用 `SavedModelConfigRow.vue`，按钮密度、对齐和响应式行为一致 |

入口阻断修复的定向 Vitest 1 项通过；未执行全量测试与界面冒烟。
