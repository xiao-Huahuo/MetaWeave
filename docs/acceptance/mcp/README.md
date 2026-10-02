# MCP 完整实现与验收（2026-10-02）

## 需求与实现对应

| 需求 | 实现 | 验收证据 |
| --- | --- | --- |
| 设置中分为客户端、服务器，复用现有布局、主题、字体和切换动效 | McpSettingsSection、SettingsPageSwitch、原设置全局样式、FormHeightTransition | 实际页面冒烟，明暗主题及 1280/768/480/360px 截图 |
| 客户端启停、服务配置增删改、stdio/HTTP、参数/环境变量/认证请求头、超时 | McpClientSettings、McpClientService、McpClientRuntime、原 MCPClient | 实际 UI 添加两种连接，真实 SDK 初始化和工具发现 |
| 草稿测试、过期提示、保存应用、取消、不丢草稿 | 临时测试连接、表单基线、独立草稿、导航保护 | 修改名称后出现过期提示；测试、保存、切换页签、取消导航均实测 |
| 状态、重连、工具策略、参数详情、错误与导入导出 | 应用拥有的连接 actor、工具目录、导入预览/冲突处理、排除凭据的导出 | SDK 同进程复用；禁用工具后旧快照被拒绝；真实同名跳过导入；刷新仍存在 |
| 正式持久化、用户覆盖与服务默认、原配置兼容 | SQLModel MCP 表、0019 迁移、SettingsService mixin、继承连接及用户覆盖 | 旧库/新库升级及回退再升级；默认不写入用户表；用户间隔离 |
| 应用生命周期、并发、取消、超时、关闭 | 独立连接 actor、单写者队列、请求取消事件、lifespan 释放路径 | 重复初始化、不同连接并行、取消、超时、失败后的正常调用和关闭均实测 |
| 每轮 Agent 稳定工具集合 | 图执行入口的工具快照、队列/Redis DTO 的完整 schema、独立子 Agent 授权范围 | 真实编译图调用真实 stdio 工具，流式/缓冲回复均通过；受限子 Agent 不获得外部工具 |
| 服务器真实启动、停止、地址及接入配置 | 独立受管 HTTP listener、官方 SDK 协议入口、McpServerService | 实际 UI 启动并验证初始化、工具发现和只读调用，通过 API 停止 |
| 凭据创建/轮换/撤销、只返回一次明文、用户与知识库范围 | 随机 Bearer token、仅存摘要、每请求授权、请求局部知识库选择 | 无凭据拒绝；轮换后旧 token 拒绝；撤销后拒绝；并发访问不同库不互相串库 |
| 以业务工具为单元、按领域管理、复用业务层 | 显式 18 项工具目录，复用 Agent schema 与知识库/图书馆/记忆服务 | 服务端不自动转发客户端 MCP 工具，不伪造聊天或编辑器上下文 |
| 访问记录、真实验证、操作完整性 | 持久化脱敏记录、真实 SDK 验证接口、REST/gRPC 管理接口 | 成功/拒绝/失败记录；真实 gRPC 管理；前端全部请求构造检查 |

## 用户追加的 UI 要求

| 原要求 | 最终实现 | 实际检查 |
| --- | --- | --- |
| 客户端取消按钮宽度不够 | 取消按钮最小宽度 104px，不收缩，文字不换行 | Playwright 实测宽度、桌面/窄屏截图 |
| 去掉高级设置及服务器中的小三角，采用娱乐功能菜单右侧大于号图标及动效 | 将 ActivityBar 原图标提取为 DisclosureChevron，侧栏与 MCP 共用，保留 14px 图标与 180ms 旋转 | MCP 无原生 details/summary；原 ActivityBar 18 项回归通过 |
| 高级设置必须有展开与折叠动效 | SettingsDisclosure 保留内容并按真实高度双向动画；220ms 高度、180ms 透明度与位移，支持快速反向及减少动态效果 | 捕获展开/折叠两次 height transitionrun；实际点击后内容正确显示/隐藏 |
| 服务器勾选框采用待办侧栏样式 | 原 TodoSidebar SVG、样式和勾选动效原样提取为 CreativeCheckbox，双方共用 | SVG 路径检查、实际界面；原 TodoSidebar 5 项回归通过 |
| 每项之间不要横线 | 工具、权限项和凭据项移除逐项分隔线 | 计算样式 border-bottom=0，截图观察 |
| 服务器下拉菜单也去三角并加动效 | 领域、工具参数、授权工具、接入配置、访问记录均使用 SettingsDisclosure | 全页面无原生 details，实际展开/折叠 |
| 取消修改按钮扩宽 | 与取消按钮共用最小 104px 样式 | 实测宽度 >=100px |
| 下方按钮统一镂空胶囊，右上方统一图标+文字无边框 | 共用 mcp-outline-button 与 mcp-text-button；菜单开关使用独立共享组件 | 实测底部透明填充/1px 边框；顶部每按钮有图标、无边框 |

## 验证结果

- 原 MCP 客户端与工具注册：4 项通过。
- 实际 stdio/HTTP、并发、取消、授权、配置继承：5 项通过。
- 调度器 schema/结果适配：2 项通过；调度器原回归：26 项通过。
- 编译 Agent 图与真实 MCP 工具执行：1 项通过（仅替换收费 LLM provider，协议、图和业务服务保持真实）。
- 实际 gRPC 管理：1 项通过。
- 迁移回归：4 项通过；新增 SDK 冻结模块收集检查：1 项通过。
- 前端请求构造：16 项通过；TodoSidebar 5 项、ActivityBar 18 项通过。
- 无网络拦截或假业务数据的完整 UI 与样式 E2E：2 项通过，单 worker 串行执行。
- 前端生产构建通过；新增 Python 模块语法检查通过；Git 差异空白检查通过。

## 验证边界与既有问题

- 全项目类型检查仍在 ImagePreviewer、OcrBlockOverlay、SmartForms 等已有代码处报错；MCP、新共享组件及相关 API 没有新增类型错误。
- 旧 Agent 大测试文件前 25 项通过，随后一个 ContextBuilder 精确字符串断言与现有用户消息时间标记格式不一致。ContextBuilder 源码未修改；本次相关图入口、工具、手动记忆及完整 MCP 执行已另外定向验证。
- 正式安装包未整体重建；已更新 SDK 固定依赖和 PyInstaller 收集配置，并检查两种客户端 transport、服务端及 session manager 均进入冻结模块清单。
- 工作区已有隐藏浏览器/编辑器侧栏造成文档额外 32px 横向范围，未改动该处正在进行的其他工作。MCP 内容本身各尺寸无横向溢出；截图使用正常的页面滚动位置。
- 明暗主题、折叠开闭及各宽度图片在本目录。新访问令牌不出现在验收截图中。
- 冒烟使用隔离数据库和模型目录；所有本任务拥有的服务端口与浏览器进程在结束前关闭。

## 截图

- [客户端桌面](client-desktop.png)、[服务器桌面](server-desktop.png)
- [客户端平板](client-768.png)、[服务器平板](server-768.png)
- [客户端手机](client-480.png)、[服务器手机](server-480.png)
- [客户端超窄](client-360.png)、[服务器超窄](server-360.png)
- [客户端浅色](client-light.png)、[服务器浅色](server-light.png)
- [高级设置展开](client-advanced-open.png)、[高级设置折叠](client-advanced-closed.png)
