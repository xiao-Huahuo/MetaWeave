# 同步提问的独立题型与界面修正

日期：2026-10-03。用户确认：**每道题只能选择或输入，同一次提问可包含不同题型。** 本记录更新首次同步提问验收中的样式与旧混合题合同。

## 逐句验收

| 用户要求 | 实现 | 真实验收 |
| --- | --- | --- |
| 不显示“手动输入”标签 | AgentQuestionBox 移除可见标签，题干提供输入框的可访问名称 | 浏览器与组件检查无标签，输入仍有明确问题名称 |
| 设置页胶囊输入框、placeholder 为“试试手动输入” | 将设置页原 input/select surface 与 focus CSS 提取到 ui-system.css，共享 form-input-capsule | 实际打开基础设置，将边框、圆角、灰底及聚焦环与输入题逐属性比较，完全相等 |
| 题干字体大小与主文字一样 | 题干及提问正文共用 font-size-base/font-chat | 浏览器 computed fontSize 与 Markdown 普通段落相等；默认及125%字号均验证 |
| 每项悬停是胶囊 | 选项使用999px圆角，延续全局强调色悬停 | 四个宽度实际悬停、截图与 computed borderRadius 验证 |
| 确定按钮是胶囊 | 确认按钮使用999px圆角，保留未答完时禁用与失败重试 | 四宽度、多题、单题多选及输入题真实操作通过 |
| 外框与设置 Skill 块一致 | 直接复用 settings-block-surface，不复制边框或模拟外观 | 实际打开 Skills 页面，对比 border、28px圆角、outline、offset、shadow和底色，完全相等 |
| 略窄于输入框 | 桌面两侧各内缩12px，窄屏/紧凑面板各8px | 1024/768px的宽度差24px，480/320px差16px，无水平溢出 |
| 下圆角被遮在输入框下层，文字高于输入框 | 独立装饰外壳z=0，composer z=1，内容z=2；外壳下延32px，内容留白 | 真实边界和层级检查通过；输入框下16px处命中 composer，标题和控制内容位于其上方 |
| 不能同题让用户做选择和填空 | UserQuestion.type=select/input；输入题无选项、选择题无文本框；后端拒绝混合参数/答案 | 旧混合题先复现两例失败，修后拒绝；选择、多选、独立输入与不同题型同批持久化通过 |
| 工具配备“输入”题型 | 完整JSON Schema暴露type枚举，前端渲染原生胶囊文本输入 | 真正模型绑定的StructuredTool保留嵌套schema；输入题只传非空text，选择题只传selected_options |
| 提示词禁止复合题与猜测必需信息 | 主提示词和工具说明要求独立题型；角色名等阻塞信息缺失时继续input追问，不因问过两次、避免空转或库中唯一对象而猜测 | 主提示词先复现缺失，修后6项提示词检查通过；正式模型节点消费该配置 |
| 输入取决于某选项时按需追问 | 仅独立且都必答的题同批；依赖选项的输入在选择后另行调用 | 浏览器选择比较后出现独立角色输入、未填时无最终输出；选择结束后只有一个请求，不出现无关输入 |
| Agent表格文字过小 | 表格、表头和单元格继承正文；原生table置于局部横向滚动容器，列最小宽度随字号变化 | 1024/320px默认及125%字号一致；十列表格可实际滚动，表头/正文列x和width一致；普通表格填满容器，无右侧空白 |
| 功能变化同步README | 更新5.1.3表格字号/横向滚动、5.2.4独立题型/条件追问/关键目标阻塞 | 阅读核对及UTF-8、diff检查 |

长选项滚动时，题干、序号、前后翻页与确定按钮保留可见。继续复用原设置展开动效及 FormHeightTransition，明暗主题和减少动画模式已操作验证。

## 合同与兼容

工具仍为 `request_user_input`，每题显式指定类型，例如：

```json
{"questions":[
  {"id":"outputs","type":"select","question":"需要哪些输出？","options":["摘要","引用"],"multi_select":true},
  {"id":"role","type":"input","question":"请输入角色名。"}
]}
```

两个问题只有在彼此独立且都必答时才同批；若角色输入仅对应某个方向，先收方向，再发输入题。输入题不接受选项或multi_select；选择题不接受文本。旧纯选择/纯输入调用会规范为新题型，旧 `options + allow_text=true` 被拒绝。返回的allow_text仅为派生兼容字段，模型工具schema不再暴露它。

问题和回答继续复用正式消息表，不改变数据库结构。检查新增合同涉及的前端客户端请求构造和真实REST；开发代理仍使用已有 `/agent` 前缀。

## 验证范围

串行、单worker完成93项相关检查：后端服务25、提示词6、全工具schema转换1；前端API/提问组件/store8、Markdown组件27、ChatInput11；Chromium实际界面15。

浏览器通过独立Vite 5174代理连接测试后端8003，正式 AgentCore、ToolCallNode、同步等待、REST和SQLite均真实运行；模型决策用确定性测试图替代，无关设置数据为测试fixture。参数合同、拒绝混合回答、阻塞等待、真实422重试、停止、条件追问与持久化均实际操作验证。该验证不等同于外部模型的指令遵从质量评测；新提示词需后端重启后加载。

初次宽表检查复现了横向裁切；display:block虽可滚动，但截图出现匿名表格与外框之间的空白，已改为统一Markdown片段路径包裹正式div滚动容器，保留原生table排版。组件回归确认流式增加行时复用滚动容器和滚动位置，终态仅包装一次。

全仓类型检查仍存在其他范围错误，不能标为通过。提问题型、组件和API未出现新增诊断；Markdown共享选择器的原生pre类型推断已在不改业务的前提下补正，已有Markdown测试88行和AgentPanel854行错误未扩展修复。完整输出位于 `runtime/test-results/question-refinement/typecheck.log`。

## 界面证据

| 宽度/主题 | 选择 | 独立输入 |
| --- | --- | --- |
| 1024px | [选择](agent-question-refined-1024.png) | [输入](agent-question-refined-1024-input.png) |
| 768px | [选择](agent-question-refined-768.png) | [输入](agent-question-refined-768-input.png) |
| 480px | [选择](agent-question-refined-480.png) | [输入](agent-question-refined-480-input.png) |
| 320px | [选择](agent-question-refined-320.png) | [输入](agent-question-refined-320-input.png) |
| 明色 | [明色](agent-question-refined-light.png) | 共享同一输入链路 |

[输入题局部预览](agent-question-refined-detail.png)、[桌面长选项与125%字号](agent-question-refined-1024-font.png)、[窄屏长选项与125%字号](agent-question-refined-320-font.png)。逐张检查字号、胶囊、外壳遮挡、按钮可用性与滚动；窄屏长选项完整保留，题干和翻页/确认始终可访问。

TODO功能项无未完成项。临时验证配置与检查脚本交付前清理，自启服务由验证脚本finally关闭；已有服务及无关并发改动保留。

## 多题自动前进与轮播补充

- 用户确认：单选选中即前进，多选／输入按Enter完成并前进；最后一题停留，仍通过确定统一提交。
- 标题与题目采用同步全宽轨道，translateX按题号平移，600ms与主页carousel同曲线；活跃页决定高度，全部草稿保留。前后箭头使用同一轨道，返回已答题不会触发再次前进。
- 动画期间锁定导航和旧页事件，transition结束／取消、700ms回退均解锁并聚焦当前页；卸载清理计时器。Enter忽略空答案、重复键与IME输入，减少动画直接切页。
- 本次定向组件6项、实际界面17项全部通过。逐帧检查存在0到负一页宽的中间位移，并验证最终精确到下一页；1024／320px回退、多选Enter、输入保留、末题确认、减少动画及原有四宽度／样式／接口场景通过。
- [桌面轮播](agent-question-carousel-1024.png)、[窄屏轮播](agent-question-carousel-320.png)已视觉检查。README同步操作方式；本次仅前端行为，后端合同及数据结构保持一致。
