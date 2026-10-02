# Agent 同步提问验收

实施与验收日期：2026-10-02 至 2026-10-03。

## TODO 逐句对应

| 用户要求 | 实现位置与行为 | 实际验收 |
| --- | --- | --- |
| 给 agent 加上同步提问工具 | `agent_service/tools/builtin/agent.py` 的 `request_user_input`，通过正式工具注册表绑定给主 Agent | 浏览器中的真实 ToolCallNode 执行该工具，收到问题 SSE |
| 调用提问工具的时候 agent 思考暂停，和等待子 agent 结束一样 | `services/user_question/service.py` 在图线程内同步等待；回答返回前，工具节点不返回 | 回答前数据库问题为 pending，后续回答节点输出为空；回答后同一 run_id 才产生结果 |
| 在输入框上方延伸出一个提问框 | `ChatInput.vue` 的 `.question-extension` 定位到输入框上方 | 四种宽度检查提问框下边缘位于输入框上边缘以上 |
| 圆角和输入框一致 | `AgentQuestionBox.vue` 与 ChatInput 共用 `--radius-xl` | 浏览器实际计算两者 border-radius 相等 |
| 无边框 | 提问表单与问题 fieldset 均为 border: 0 | 浏览器计算提问框 border-width 为 0px；已检查截图 |
| 出现时有平移上浮动效 | 复用 SettingsDisclosure 的共享动效 CSS，设置从下方 8px 平移到 0 | 逐帧记录 transform/opacity，确认初始向下偏移且透明，最终偏移归零；减少动画模式有效 |
| 顶部显示问题 | 问题文字位于 fieldset 的 legend，紧接导航栏 | 单题、多题实际页面均显示问题标题 |
| 下面有 N 个选项，由 Agent 决定 | 工具的 questions[].options 合同与选项 v-for，无硬编码业务选项 | 浏览器同批次分别显示两个、三个选项；工具节点读取测试图提供的参数 |
| 可以同时提多个问题 | 单次工具调用接收问题数组，前后端统一提交一批答案 | 三题真实 API 提交只产生一次回答请求 |
| 多个问题左上角标记序号 | 导航栏左侧显示当前题号 / 总题数 | 浏览器逐题检查 1 / 3、2 / 3、3 / 3 |
| 右上角可以回退或者前进 | 使用现有 IcIcon 和 v1-icon-button，题首、题尾禁用越界按钮 | 实际点击下一题、上一题，单选、多选和文本草稿保留 |
| 多个问题右下角显示“确定” | footer 使用右对齐布局 | 四种宽度的末题确认截图已检查 |
| 未答完所有问题时不能点 | 前端逐题计算 complete，原生 disabled；后端也拒绝漏答 | 前两题作答后仍不能提交，第三题填写后启用；真实 REST 对漏答返回 422 |
| 组件样式和动效从设置页面找 | 复用设置页面的 CreativeCheckbox、FormHeightTransition、无边框 form-input-surface 与 SettingsDisclosure 动效；后者提取共享 CSS 保留原默认行为 | 明暗主题截图、上浮逐帧检查及组件回归通过 |

用户已确认：单题单选立即提交；多题全部答完后点击确定；Agent 可以启用多选和手动输入。单题多选／文本输入也需要确定按钮，已实际操作验证。

## 数据与生命周期

- 问题、真实回答和终态经 MessageService 保存到现有 MessageRecord 表的 `metadata_json.user_question`；未新增数据表，因此无需数据库迁移。工具结果也沿用正式工具消息持久化。
- AgentCore 拥有提问服务。内存索引只定位活跃等待者，选项草稿是未提交的临时 UI 状态；关闭、取消、超时和异常均清理等待索引。
- REST 投递回答，图线程独占数据库写入；锁内仅检查和更新内存，持久化及回调均在锁外执行。重复提交、跨会话、跨用户、非法选项和非法多选被拒绝。
- 主 Agent 提供用户交互；原生子任务工具目录不开放同步提问，以免无人消费的子对话阻塞。子任务需要用户决策时仍由主 Agent 询问。
- 开发代理沿用 `/agent` 前缀。浏览器的 SSE、问题查询、回答、停止和数据库验收请求均经过前端开发端口，非浏览器拦截的假回答。
- 默认人工等待上限一小时，REST 持久化确认上限三十秒，由 AgentConfig 管理并拒绝非有限／非正配置。等待人工回答期间暂停前端十分钟流式超时计时。

## 执行结果

均串行、单 worker 执行，共 80 项通过：

| 验证 | 通过数 |
| --- | ---: |
| `python -m pytest tests/test_user_question_service.py -q` | 14 |
| `tests/test_agent_tool_registry.py` | 3 |
| `tests/test_agent_rest_stream.py` | 3 |
| `tests/test_child_agent_tool_types.py` | 1 |
| 新增 Agent API、提问组件、提问 store 定向 Vitest | 7 |
| 现有 `chat.spec.ts` | 31 |
| 现有 `ChatInput.spec.ts` | 11 |
| Chromium 真实页面冒烟 | 10 |

浏览器测试使用 `tests/user_question_smoke_server.py` 的确定性测试图替代外部模型决策，正式 AgentCore、工具执行、SSE、REST 和 SQLite 均真实运行。验证了单题即时恢复、多题翻页、单题多选／文本确认、真实 422 后保留草稿重试，以及停止后数据库取消终态。未消耗真实模型额度；不将该验收视为外部模型主动选择提问工具的质量评测。

复现：先在项目根目录运行 `python -m uvicorn tests.user_question_smoke_server:app --host 127.0.0.1 --port 8002`，再在 editor 目录运行 `npx playwright test e2e/agent-user-questions.spec.ts --project=chromium --workers=1 --reporter=line`。请使用空闲的验收端口，不替换正在使用的正式服务。

全仓 `npm run type-check` 未通过，存在 87 条诊断（包括重复项目诊断）。提问新增模块未报错；本次涉及的 AgentPanel 报错来自 HEAD 已存在的 `:selected-session-id="activeSessionId"` 可空值绑定，未改动该行。完整输出保存在 `runtime/test-results/user-question-typecheck.txt`。TODO 功能项均已完成；全仓类型检查不能标为通过。

## 已检查的界面截图

| 宽度／主题 | 问题与导航 | 全部作答后的确认 |
| --- | --- | --- |
| 1024px | [问题](agent-user-question-1024.png) | [确认](agent-user-question-1024-confirm.png) |
| 768px | [问题](agent-user-question-768.png) | [确认](agent-user-question-768-confirm.png) |
| 480px | [问题](agent-user-question-480.png) | [确认](agent-user-question-480-confirm.png) |
| 320px | [问题](agent-user-question-320.png) | [确认](agent-user-question-320-confirm.png) |
| 明色主题 | [问题](agent-user-question-light.png) | 同一真实回答链路 |

逐张检查了提问框、题号、选项、输入与确认按钮的可见性及换行，无水平溢出或缺失。测试服务和 Playwright 自启服务在交付前关闭，保留验收脚本与截图。
