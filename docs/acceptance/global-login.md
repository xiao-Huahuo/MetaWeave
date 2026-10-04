# 全局登录与五页初始化验收

日期：2026-10-04。本文逐句对应用户已确认的要求，区分源码、自动化验证和真实界面证据。以下实测来自本次 Electron + 真实 Python 服务，以及后端同源端口 18764 的编译后 SPA；没有使用早先纯前端原型结果代替本次验收。

## 五页需求与实际结果

| 编号 | 用户要求 | 实现与正式接口 | 本次实际结果 |
| --- | --- | --- | --- |
| P1-01 | 登录、注册均为 01，右上前后导航和序号。 | `CredentialsStep.vue`、`AuthFormShell.vue` 保留 01；未认证箭头禁用。认证后可退回 01，清空密码并显示当前用户名；未编辑凭据可直接回 02，不调用登录/注册或续期；确定仍是手动认证。 | 已通过。编译后 SPA 实际完成 02→01→02，无重新认证；对应断言通过。 |
| P1-02 | 用户名、全局密码；注册确认密码。 | `AuthView.confirm` 对确认密码不一致留在表单，经 `api/auth.ts` /受限桌面 IPC 调用 `/auth/register`、`/auth/login`；成功后清密码。 | 已通过真实注册、登录和改密后重新登录。密码及 Key 未写浏览器存储。 |
| P1-03 | 首次初始化五页，完成后只登录；未完成恢复进度。 | 正式 `Account` 持久化 `onboarding_step/onboarding_completed`；保存后 `/auth/onboarding` 顺序推进，6 为完成。`App.vue` 等真实身份和后端档案读取完成才进主页。 | 实际完成五页并进入主页，重启/过期时回登录；完成账号重新登录直接进入。恢复与禁止跳页状态回归通过。 |
| P2-01 | 知识库名称和本机绝对目录。 | `KnowledgeLibraryStep.vue` 读取正式档案与 `/settings/onboarding/defaults`；`AgentConfig.Storage`、`SettingsService` 解析绝对路径，`/settings/profile/knowledge-dir` 同时保存名称和目录。 | 已通过：库名称、绝对目录实际落库并读回一致。 |
| P2-02 | 原生目录选择器。 | 复用 `window.agentEditorDesktop.selectDirectory`，选择回填，确定正式保存。 | 已打开真实 Windows“选择文件夹”窗口，实际选择 `selected-knowledge`，绝对路径回填和确定保存成功。 |
| P2-03 | 登录/知识库同高 480px，注册自然伸缩；无横向溢出。 | `AuthFormShell.compact/updateHeight`、`FormHeightTransition` 与原高度 CSS；登录/知识库关闭内部滚动，长页面保留 Y 滚动。 | 编译后 SPA 实测 login 480px、library 480px、register 自然 509px；320/480 视觉检查通过，320/480/768/1024 的页面横向 overflow 均 false，第四页 Y 滚动合理。最后发现并修正焦点导致 viewport.scrollLeft 裁切，见末尾复验记录。 |
| P3-01 | 大/小/视觉模型可展开，各有模型名、URL、API Key 和独立保存。 | 复用 `SettingsDisclosure`；`saveOnboardingModel` 向 `/settings/llm/config` 仅提交所选角色字段，不覆盖其他角色。 | 三组控件实际保存并正式读回符合；角色独立请求回归通过。第二账号不配任何模型也能完成初始化。 |
| P3-02 | MinerU 可展开，Key、模型、VLM、OCR、识图均保存。 | `/settings/vlm/config` 保存 `enabled/api_key/model`；`/settings/profile/ingestion` 保存 OCR/识图。原 2px 分组边框和折叠组件保留。 | 控件全部真实落库和读回；两类接口及全部字段请求回归通过。 |
| P3-03 | 保存按钮真实落库，页面确定保存全部块后再前进。 | `AuthView.saveModel` 等待正式响应，不推进页码；页面确定串行保存四块，有失败留在当前页。 | 真实五页流程和字段读回通过；保存失败不推进与独立保存断言通过。 |
| P4-01 | 原句：“第四页：必要设置。外观: 显示外观-主题中的所有内容。” | 对照 `AppearanceSettingsSection` 的主题组：明亮/暗色/跟随系统、主/柔色颜色选择与 HEX、保存、重置均完整呈现。其他外观组不扩展进该句。 | 已通过：dark 已读回；编译 SPA 设置 system 和 HEX `#2850ff/#cfd8ff`，保存后 GET profile 精确读回。 |
| P4-02 | 主题预览使用全局机制，保存和重置真实有效。 | 复用 `settings.previewAppearanceColors/setThemeMode`；`/settings/appearance/config` 持久化账号模式和颜色。重置立即清空两个颜色覆盖，再显示默认色，成功后同步正式档案颜色。 | 实际显示“主题色已重置”；system/HEX 保存读回通过。重置请求及不推进页码断言通过。 |
| P4-03 | 搜索默认关闭，开启才显示代理输入并保存。 | `PreferencesStep` 条件显示代理；`/settings/web-search/config` 写 `web_search_enabled/proxy_url`。 | 第二新账号实际 search=false；第一账号代理实际保存读回符合。 |
| P4-04 | 长期记忆开关保存。 | `/settings/memory/config` 经 `SettingsService` 持久化 `long_term_memory_enabled`，恢复读取同一接口。 | 已真实保存并读回符合。 |
| P4-05 | 敏感词库、安全审核改为用户级，共享词库内容保留。 | `/settings/safety/config` 保存当前账号开关；共享词库内容另用 sensitive-words 接口。`SafetyService`、检查器、输出审核和 Agent 节点消费用户有效值。 | 两账号配置及五页安全控件真实落库读回符合；用户安全行为回归通过；共享内容 payload 不写全局禁用标志。 |
| P4-06 | DSH 仅完整 DeepSeek 配置可开，不符合条件置灰且关闭。 | `AuthView.dshAvailable` 与服务端相同资格规则；模型变更在事务内关闭不兼容设置。 | 新账号无模型时 DSH 灰且禁用；实际把配置改为 gpt4.1 保存后，基础设置 DSH disabled/off，数据库 false。 |
| P5-01 | 完成页烟花，明确点击进入主页。 | `CompletionStep` 保留效果，进入调用 `/auth/onboarding` 步骤 6 成功才满足 `canEnter`。 | 已实际进入主页，完成状态落库；[完成页截图](assets/global-login/completion.png)。 |
| UI-01 | 固定亮色表单、光晕、小确定 hover、平滑切页/高度、指定慢背景。 | 原亮色表单、84px 确定、600ms 轨道/测量高度保留；真实 Vue `LineWaves` speed=0.15，生命周期释放 GPU/事件/动画。 | 实际入口及多宽度视觉通过，passwordEmpty、卡片/慢背景/小确定符合；最终编译 SPA `pageErrors=[]`。 |

## 全局账号、安全与退出

| 编号 | 用户要求 | 实现与正式接线 | 本次实际结果 |
| --- | --- | --- | --- |
| G-01 | `user_id` 从用户名与创建时间共同编码为 8 位数字。 | `AuthService` 从规范化用户名及持久化创建时间生成 UID，数据库唯一约束及冲突处理；renderer 消费服务结果。`AccountIdentity.vue` 在设置左下展示。 | 已显示真实姓名与 UID **72415176**；[身份截图](assets/global-login/settings-account.png)。生成/冲突后端回归通过。 |
| G-02 | 旧身份/业务数据全删，从新开始。 | Alembic `20261004_0020_global_auth` 清旧关系并移除旧 vault profile；主任务按已核验边界清旧知识/向量/附件/密码库/备份等，保留程序与模型，无迁移绑定 UI。 | 已执行生产库升级和托管资源清理；验收使用新注册账号。遗留 browser profile 及旧 vault JWT 明确前缀缓存已清理，不清其他浏览器存储。 |
| G-03 | 登录密码就是密码库主密码，保留直接派生 Fernet；改密后内容不丢。 | 密钥留在 AuthService，Vault 使用同一 app session；旧独立 setup/unlock/reset/debug/lock API/UI 移除。`/auth/password` 验旧密码、原子重加密、撤销会话/设备。 | 实际新建密码库 item→安全页改密→旧 token 401→新密码登录，item.fields JSON 完全相等；[密码库截图](assets/global-login/vault-account.png)。浏览器已撤销 token 的 401 幂等退出断言通过，不误报密码修改失败。 |
| G-04 | 自动登录凭据固定 30 天，自动登录不延长。 | `AuthDevice` 保存原 expiry；safeStorage 解封后 `/auth/restore` 不续期；仅手动 register/login 重签。 | 实际重启自动登录，remember expiry 原值不变。 |
| G-05 | “到期之后就不自动登录，必须手动确认才续期自动登录。” | metadata/payload 到期只返回 username+expired；密码为空，不 restore 登录、不重签。 | 测试库将 expiry 置过去：仅登录、用户名回填、提示到期；填写密码仍不登录，点击确定才续 30 天；[到期截图](assets/global-login/expired-login.png)。 |
| G-06 | “自动登录的时候那个 loader 转圈应该等待 2s。” | loader 在确定左侧；`restore` 2000ms 下限，慢验证继续等，正式档案就绪才进入；generation/token 拒迟到结果。 | 真实自动 loader **2144ms**，passwordEmpty；[loader 截图](assets/global-login/auto-login-loader.png)。1999ms/慢验证/晚回包定向回归通过。 |
| G-07 | 记忆/派生密钥加密保存，不持久化主密码、不将密钥给 renderer。 | Electron safeStorage，密文走 nonce 限制 API 写正式设备表；IPC 只返回公开会话，renderer token 仅内存；加密不可用拒记忆。 | 真实 Windows OS 加密写正式 DB，桌面验收记录 sealed blob 380 字节；重启解封通过，私有字段/来源限制回归通过。 |
| G-08 | 关闭保留，主动/离线退出真实撤销并避免自动回来。 | 正常关闭只释放资源；退出清 cookie、撤销设备及关联会话；后端离线调用同一正式服务的 CLI，失败才报告。 | 主动退出 DB blob_length=0/revoked=1；kill 后端再退出 CLI 仍为 0/1；服务和 Electron 重启后 session=null；[离线退出](assets/global-login/offline-logout.png)、[退出登录](assets/global-login/login-after-logout.png)。 |
| G-09 | 退出/切号清私有缓存，旧回包不能回填。 | workspace 同步 reset 清树/标签/内容/预览/搜索/可视化，停 EventSource/轮询并 abort；真实 chat/session 清/abort 私有状态。epoch/user/token 校验与 API stale 拒收；SSE finally cancel 底层 body 再释放 reader。 | 私有数据缺陷先失败复现再修，workspace4/chat2、stale stream cancel 回归通过；初始化仅清 `metaweave_vault_token_` 旧 JWT 前缀、保留其他 cache且不写新 token 的回归通过。主动/离线退出重启无会话已实际通过。 |
| G-10 | 真实 API、开发代理、正式后端 origin 和浮窗同步。 | API 路由/`/auth` proxy 集中登记；Bearer/credentials覆盖 JSON/multipart/stream/binary；读取实际 backendOrigin，EventSource带 credentials。浮窗使用 trusted main 无数据进度通知再 GET/me；IPC只允许正式入口顶层 frame。 | 真实 Electron 与同后端 origin 18764 的编译 SPA均通过；实际打开 `/?floating=1` 浮窗，主页 logout 后 float privateRoot=false，pageErrors=[]。Desktop16、backendRuntime5 回归通过。 |

## 验证与发布边界

- 最终前端七个文件 **44 项**全部通过，严格单 worker、逐文件串行：client6、authAPI9、authStore10、AuthView7、onboarding6、workspace4、chat2。所有新增 nav/reset/01/browser401/legacytoken/streamcancel 均已复验。
- 最后一项真实模型截图发现焦点使 viewport.scrollLeft 非零。已单独先取得 120→期待0 的失败基线，再仅加 `@scroll` 复位 X，不改 CSS/高度/切页 transform，Y=67 保持；该单项 targeted 回归通过。最后完整串行构建和编译页面模型截图复验已通过，scrollLeft=0，字段及边框完整。
- 后端 auth12、grpc10、REST8、assets2、vault11、migration5 已通过；桌面身份 **16**、后端启动参数 **5** 已通过；主任务最后 transport2+safety1+grpc imports3 合批 **6** 已通过。以上按模块记录，不把重复回归相加成不重复总数。
- 最新完整 `npm run build` 已成功，串行执行 vue-tsc 与 Vite，5311 模块；最后 X 修复后的重建也已通过。
- 打包清单已核对 auth/model/device CLI/gRPC imports、整目录 Alembic、新 Electron 模块。自启动及离线 CLI 的 host/port/runtime DB/nonce、生产 frontendOrigin、旧健康服务 nonce probe 三项发布参数缺口已修正并回归。
- 真实界面已核对 [320](assets/global-login/preferences-320.png)、[480](assets/global-login/preferences-480.png)、[768](assets/global-login/preferences-768.png)、[1024](assets/global-login/preferences-1024.png)，小屏无横向溢出、长页正常 Y 滚动。初始 login 截图在 01 修复前取得，不作为修复后的序号证据；[注册](assets/global-login/register.png)、auto/expired 截图和编译 SPA实际读回已确认01。
- 本次完成源码 Electron + 真实服务及编译 SPA验收；没有用这些结果声称独立 Windows exe/NSIS 安装器已经做过安装烟测。所有主任务拥有的端口已停止；前端子任务未开端口。

最终补验：模型页焦点自动滚动的横向裁切已修复，定向回归先失败后通过（新增1项）；最后完整 npm run build 通过（vue-tsc 后 Vite 5311模块），构建后的同源 Electron 再次真实输入大模型与 MinerU 字段，viewport.scrollLeft=0，修复后的模型截图已肉眼确认字段与边框完整。所有自开服务、Electron 进程和测试运行目录已清理。
