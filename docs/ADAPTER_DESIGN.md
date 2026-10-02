<!--
文件功能：定义 MetaWeave 以 DeepSeek Harness 作为代码子 Agent 运行内核的完整设计，包括需求来源、选型依据、持续对话、权限继承、进程监督、协议映射、打包升级、安全边界和验收标准。
使用说明：实现或修改 DSH Adapter、ChildAgentManager、DSH 发行配置、Windows 运行包及相关测试前必须阅读本文；任何改变模型范围、权限语义、进程生命周期或会话持久化的修改都必须同步更新本文。
-->

# DSH Adapter 详细设计

## 1. 文档目标

本文说明 MetaWeave（下文简称 MW）为什么选择 DeepSeek Harness（下文简称 DSH）作为代码子 Agent，以及 MW 应当如何启动、控制、续接和回收 DSH。

实现者应当能够根据本文确定以下问题的唯一答案：谁创建子 Agent、谁调用模型、谁修改代码、权限从哪里来、一轮回答结束后进程是否退出、父 Agent 如何继续追问、应用退出时如何保证没有残留进程，以及 DSH 升级后需要重新验证哪些行为。

本文已经确定以下核心决策：

1. DSH 是 MW 的专用代码子 Agent，不是通用模型代理，也不是 MW 工具的远程调用方。
2. DSH 只使用自己的文件、搜索、PowerShell、Git 和测试执行能力，不调用任何 MW 工具、MCP 服务或业务接口。
3. DSH Adapter 只支持 DeepSeek API。MW 中其他模型配置不进入 DSH。
4. 一个 DSH 子 Agent 对应一段可持续追问的 Conversation；一次回答只是其中一个 Turn，不代表子 Agent 或 Runtime 已结束。
5. 中大型代码改动应尽量在同一个 DSH Conversation 中完成分析、修改、测试、失败修复和最终总结，不能把每一步都拆成失去上下文的新进程。
6. DSH 的有效权限继承 MW 父 Agent 当前的访问模式，子 Agent不得自行提高权限。
7. MW 负责 DSH Runtime 进程及其全部后代进程的生命周期；DSH 输出结果后可以继续驻留，但 MW 关闭、显式停止或资源回收时必须彻底退出。
8. DSH Python SDK客户端与 Windows Runtime ZIP都进入 MW主 EXE；应用启动时不解压，第一次安装或第一次使用 DSH子 Agent时才从 EXE内置资源校验并懒解压。
9. Windows Runtime使用固定 DSH提交的生产依赖闭包生成，携带独立 Node 24与无 symlink的 DSH Node闭包，必须提供文件编辑、搜索、PowerShell、Git、测试和构建能力；MW不从零实现 DSH SDK或代码 Agent循环。
10. 同一个受管 Runtime同时提供 SDK JSON-RPC控制面和 DSH Web观测面。JSON-RPC是唯一写控制面；DSH Web对 MW 托管 Session实行服务端只读，只用于查看轨迹、工具调用、命令输出、diff、产物和最终回答。
11. DSH 处于开发阶段，因此 MW 固定经过验证的源码提交、SDK、Cordis 配置、Windows Runtime和资源哈希，不在用户设备上追踪上游主分支，也不在运行时安装任意 npm插件。
12. DSH coding agent是用户级显式选择，默认关闭；关闭时后端拒绝创建和继续 DSH Conversation，开启后只在应用界面启动完成时后台安装内置 Runtime。

## 2. 需求来源

### 2.1 MW 需要一个真正擅长代码工作的子 Agent

MW 父 Agent承担对话、任务理解、资料组织和多种业务能力。代码修改只是其中一类工作。让父 Agent 同时长期承担仓库探索、跨文件修改、命令执行、测试诊断和反复修复，会扩大父上下文、占用主对话注意力，并使代码任务和用户的主线讨论相互干扰。

因此 MW 需要一个独立的代码执行角色。父 Agent负责说明目标、约束和验收标准；代码子 Agent负责进入工作区、理解代码、实施修改、运行测试并报告结果。

### 2.2 不能依赖用户另外购买或登录 Codex、Claude Code

DSH 已经提供调用宿主机 Codex 和 Claude Code 的 provider，但这些 provider 使用宿主机相应产品的安装、登录状态和额度。对于 MW 用户，这意味着除了配置 MW 模型，还要安装并登录另一套产品，并承担另一套额度与兼容性要求。

MW 已经要求用户配置 DeepSeek API。代码子 Agent应直接复用这份配置，而不是再要求 Codex 或 Claude Code 账户。因此本设计选择 DSH 自身作为代码 Agent 运行内核，并让 DSH 直接调用 DeepSeek API。

### 2.3 用户不应手工安装或维护 DSH

DSH 是 MW 的可选内部运行组件，不是 MW 的主 Agent，也不是要求用户另行配置的独立产品。用户只安装 MW 主程序，不需要自行安装 DSH、Node、WSL 或 Docker，不需要执行 npm install、配置 Cordis 或维护 DSH 会话目录。

Python SDK客户端、Adapter代码和固定的 Windows Runtime SDK随 MW主 EXE交付。第一次创建 DSH子 Agent时，MW检查 Runtime是否已经解压；未安装时从 EXE内置 `sdk.manifest.json`与 `sdk.zip`完成哈希校验、解压、自检和原子安装。用户也可以提前在“设置—存储管理—SDK 与运行组件”中安装、修复或卸载，不需要联网或另行下载。

按需安装不等于动态追随上游。每个 MW版本只接受 EXE内置清单中固定的 Runtime版本和哈希；用户不接触 PyPI、npm或 DSH插件市场。SDK资源未安装、解压失败或被用户卸载时，仅 DSH代码子 Agent不可用，MW知识库与其他能力继续正常工作。

### 2.4 中大型代码修改需要持续上下文

真实代码任务通常不是“一问一答”。一次中大型修改往往包含：阅读入口、定位调用链、确定方案、修改多个文件、运行测试、分析失败、继续修复、再次测试和汇总结果。

如果每一步都启动一个全新的 DSH，后续步骤必须重新阅读仓库和重新理解前因，既浪费模型额度，也容易出现前后决策不一致。因此 MW 必须保留稳定的 DSH Conversation，使父 Agent可以在同一上下文中继续提问，例如“修复刚才失败的测试”“继续检查另一条调用链”或“根据测试输出完善实现”。

### 2.5 子 Agent必须继承父 Agent的权限选择

MW 已经向用户提供只读、沙盒和完全访问三种模式。用户对父 Agent作出的权限选择也必须约束代码子 Agent，否则父 Agent处于沙盒模式而 DSH 获得完整本机权限，会破坏用户对权限界面的理解。

DSH 不调用 MW 工具，因此不能依赖 MW 工具执行器逐次拦截。Adapter 必须把 MW 模式映射为 DSH 自身的沙箱模式，并选择对应的 DSH 文件系统和 PowerShell 执行器。

## 3. 目标与非目标

### 3.1 设计目标

- 父 Agent能够创建一个专门负责代码的 DSH 子 Agent。
- 子 Agent能够在指定工作区读取、搜索和修改代码，并运行 PowerShell、Git、测试和构建命令。
- 子 Agent只使用 DeepSeek API，并复用当前用户在 MW 中生效的大模型配置。
- 同一个子 Agent能够在多轮 Turn 之间保持 Conversation。
- 中大型修改默认复用同一 Conversation，直到修改和验证形成闭环。
- DSH 权限不得高于父 Agent当前权限。
- 一轮完成后可以保留热 Runtime；Runtime 被回收后仍可从持久会话冷恢复。
- MW 能够在取消、超时、崩溃、应用退出和资源回收时终止完整进程树。
- Windows Runtime能够在真实仓库中读取、搜索、创建和修改代码，执行 PowerShell、Git、测试和构建，并依据失败结果继续修复。
- 用户无需手工安装或配置 DSH、Node、Codex、Claude Code、WSL 或 Docker；DSH受管资源由 MW按需安装。
- 用户能够从 MW打开当前 DSH子 Agent的原生 Web轨迹界面，且观察操作不会绕过 MW创建 Turn、修改权限、发送 Prompt或改变 Conversation状态。
- SDK受管资源支持查看状态、解压进度、版本、内置包大小、磁盘占用、安装位置、修复和卸载；内置产物经过哈希与签名校验。
- DSH 升级经过固定版本、构建闭包和真实任务测试，不影响已经安装的 MW。

### 3.2 明确不做的事情

- 不调用 Codex 或 Claude Code。
- 不为 OpenAI、Anthropic、Kimi 或通用 OpenAI-compatible API 提供独立适配。DSH 始终使用 deepseek-official 的请求语义；自定义 base_url 只有在服务端兼容这套 DeepSeek 请求语义时才能工作。
- 不把 MW 工具、数据库、设置服务、密码库、知识库或 MCP Server暴露给 DSH。
- 不允许 DSH 创建自己的子 Agent。
- 不把 DSH Web变成第二个主 Agent或写控制面；不允许 MW托管 Session从 Web发送 Prompt、取消 Turn、回答审批、创建会话、修改模型/权限/设置或管理插件。
- 不把 DSH TUI、交互式审批界面、设置中心或插件市场带入 MW。
- 不在用户设备上从网络、PyPI或 npm获取 DSH；只解压 MW主 EXE内置并由固定清单校验的 Windows Runtime资源包。
- 不把一次 Turn 完成误认为整个 Conversation 完成。
- 不承诺在 Windows 受限模式下阻止 DSH 读取当前用户本来可以读取的所有文件，也不把文件模式描述成网络、注册表或 IPC 沙箱；这些上游限制必须在权限说明中如实呈现。

## 4. 为什么选择 DSH

### 4.1 DSH 已经具备代码 Agent 的完整循环

DSH 不是单纯的模型客户端。它具有 Agent Loop、会话日志、流式事件、文件工具、代码搜索、PowerShell 执行、子进程管理、沙箱策略和上下文压缩能力。MW 不需要重新实现一套代码 Agent，只需要为 DSH 提供工作区、DeepSeek 配置、权限模式和生命周期管理。

### 4.2 JSON-RPC 适合宿主控制

DSH 的 JSON-RPC Runtime 使用标准输入输出传递请求、响应和通知。MW 可以可靠地完成握手、发送 session/prompt、接收 session.event 与 session.status，并在结束时请求 shutdown。它不需要解析终端画面、模拟键盘输入或依赖交互式 UI。

### 4.3 Cordis 可以裁剪成 MW 专用运行时

DSH 的能力由 Cordis 插件组合。MW 只装载代码任务、SDK JSON-RPC控制和只读 Web观测所需的组件，同时明确排除内部子 Agent、用户插件、MCP、TUI、审批、运行时升权和无关工具。MW专用组合在同一进程中装载 JSON-RPC Server与 Web Server，使 SDK和浏览器观察同一个 Agent、Session和事件流。能力面由受管 SDK资源包中的只读配置决定。

### 4.4 DSH 可以直接使用 DeepSeek

DSH 提供 deepseek-official 模型路由，可以使用 DEEPSEEK_API_KEY、DEEPSEEK_BASE_URL 和具体模型名。模型 ID可以按请求传入，未列入展示目录的 DeepSeek 模型 ID仍可透传。

### 4.5 开发版风险可以通过固定版本控制

DSH 仍处于快速开发阶段，但 MW 不需要动态跟随。固定提交、固定 SDK客户端、固定配置、固定 Windows Runtime和哈希清单可以把“上游每天变化”转化为“MW 主动生产新 SDK并重新构建 EXE时才变化”。懒解压只改变安装时机，不改变版本固定策略。

## 5. 宏观设计思路

可以把整个设计理解为：MW 在需要写代码时，给父 Agent请来一名专门的代码工程师。

父 Agent把任务目标、工作区和权限交给这名工程师。工程师拥有自己的代码工具和 DeepSeek 模型，不借用父 Agent的工具。工程师完成一轮工作后向父 Agent汇报，但不会立刻离开；父 Agent可以继续追问，让它基于刚才的上下文修测试或继续修改。

为了避免机器上长期堆积进程，空闲工程师可以暂时下线。它的 Conversation 已写入独立会话目录，下次追问时 MW 重新启动 DSH，并用原会话继续工作。对父 Agent而言，这仍然是同一个子 Agent。

权限由父 Agent决定。父 Agent是只读模式，DSH 只能分析；父 Agent是沙盒模式，DSH 可以修改工作区并在工作区内运行命令；父 Agent是完全访问模式，DSH 才获得完整文件访问能力。DSH 无权自己把沙盒模式改成完全访问。

## 6. 总体架构

~~~mermaid
flowchart TD
    U[用户] --> P[MW 父 Agent]
    U --> OW[DSH 只读 Web]
    P --> M[ChildAgentManager]
    M --> A[DshChildAgentExecutor]
    A --> C[DshConversationRegistry]
    A --> R[DeepSeekConfigResolver]
    A --> I[DshRuntimePackageManager]
    C --> S[DshRuntimeSupervisor]
    S --> J[Windows Job Object]
    I --> S
    J --> D[DSH MW Runtime]
    D --> Q[JSON-RPC控制面]
    D --> H[Web只读观测面]
    Q --> A
    H --> OW
    D --> L[DSH Agent Loop]
    L --> F[DSH 文件与搜索工具]
    L --> PW[DSH PowerShell与测试工具]
    L --> K[DeepSeek API]
    D --> E[DshEventMapper]
    E --> M
    M --> P

    X[MW 工具/数据库/MCP] -. 不暴露 .-> D
~~~

架构中有两条边界：

1. MW 控制边界：负责子 Agent身份、父子关系、权限、进程、事件和用户可见状态。
2. DSH 执行边界：负责代码推理、文件操作、命令执行、测试、会话上下文和 DeepSeek 请求。

两边通过 JSON-RPC 交换控制消息与事件，不交换 MW 工具调用。Web只读取同一 Runtime发布的 Session轨迹，不经过第二个 DSH进程，不取得控制权，也不直接读取 MW数据库。

## 7. 核心概念

### 7.1 Child Agent

Child Agent 是父 Agent看到的稳定子角色。它具有稳定 child_id、所属用户、父会话、工作区、权限模式和 DSH 会话标识。只要用户没有明确终止或删除，它就可以被再次追问。

### 7.2 Conversation

Conversation 是 DSH 持久会话。它包含多个按顺序执行的 Turn。Conversation 的身份由 dsh_session_id 表示，并绑定一个独立 session_root。

### 7.3 Turn

Turn 是父 Agent向该子 Agent发送一次指令后，到 DSH 回到 idle 为止的一轮活动。每个 Turn 有独立 turn_id、输入、开始时间、结束原因和结果。Turn 完成只意味着本轮可以向父 Agent交付结果。

### 7.4 Runtime

Runtime 是承载 Conversation 的 DSH Windows进程。它包含 Agent Loop、SDK JSON-RPC Server和只读 Web Server；三者共享同一个 Session与事件流。一个活动 Conversation 同一时间最多有一个 Runtime。Runtime 可以经历多轮 Turn，也可以在空闲后被回收并在下一次追问或用户打开历史轨迹时重建。

### 7.5 热续接与冷恢复

热续接是向仍在内存中的 Runtime 和同一 DSH Session 发送下一条 prompt。冷恢复是在 Runtime 已退出时，用相同 session_root 和 dsh_session_id 启动新 Runtime，再继续发送 prompt。

## 8. 父 Agent侧组件

### 8.1 ChildAgentManager

ChildAgentManager 仍然是父 Agent创建、列举、追问、停止和等待子 Agent的唯一入口。它不依赖 DSH SDK 类型，只使用 MW 自己的合同和事件。

现有 ChildAgentManager 把执行器返回视为永久 COMPLETED，这不适合持续对话。实现时必须把“子 Agent生命周期”和“Turn 生命周期”分开：

- 子 Agent状态：created、starting、idle、running、offline、stopped、failed。
- Turn 状态：created、running、completed、failed、stopped、outcome_unknown。

idle 表示子 Agent存在且当前没有执行 Turn；offline 表示 Conversation 存在但 Runtime 已回收；stopped 和 failed 才是终止状态。

ChildAgentManager 继续执行权限不高于父级、子 Agent不能再创建子 Agent、同一 Conversation 内 Turn 串行等通用规则。

### 8.2 DshChildAgentExecutor

DshChildAgentExecutor 是 MW 的 DSH provider。它把 MW 子 Agent合同转换为 DSH Conversation 和 Turn 操作，但不把 DSH 类型泄漏给父 Agent。

它负责：

- 创建或取得稳定的 DSH Conversation。
- 读取用户当前生效的 DeepSeek 大模型配置。
- 解析并固定工作区根目录。
- 根据父 Agent当前模式解析 DSH 沙箱模式。
- 获取热 Runtime，或请求 Supervisor 冷启动。
- 发送 session/prompt 并等待本轮达到权威终点。
- 将 DSH 事件映射为 MW 事件。
- 折叠本轮最终助手文本并校验 output_contract。
- 在异常路径中请求 Supervisor 关闭或隔离故障 Runtime。

Executor 不直接执行文件或命令，不实现 MW Tool Bridge，也不允许 DSH 访问 MW 内部服务。

### 8.3 DshConversationRegistry

DshConversationRegistry 保存 Child Agent 与 DSH 会话的稳定对应关系。正式数据必须进入 MW 后端数据库，不能只保存在内存或临时 JSON 文件中。

每条记录至少包含：

- child_id 与 parent_run_id。
- user_id 与 MW session_id。
- dsh_session_id。
- session_root 的受控位置或可重建标识。
- workspace_root。
- 当前有效 access_mode。
- DSH manifest 版本。
- Conversation 状态、最后活动时间、最后 Turn 序号和 last_durable_seq。
- 是否允许冷恢复，以及最近一次失败摘要。

进程句柄、管道、Job Object 和内存队列只属于当前进程内的 Supervisor，不写入数据库。

Registry 必须保证一个 Conversation 同时只有一个 Runtime owner、一个活动 Turn。Conversation 为 running 时不接受第二条追问，而是返回 DSH_CONVERSATION_BUSY；调用方观察到 idle 后再提交。本文不设计可能在 MW 与 DSH 崩溃边界重复投递的持久消息队列。

### 8.4 DeepSeekConfigResolver

Resolver 按 user_id 读取 MW 当前生效的大模型配置，遵循项目已有的“用户覆盖优先、服务默认保底”规则。

DSH 只读取以下字段：

- api_key。
- base_url。
- model_name。

provider 不参与自由路由；DSH 路由固定为 deepseek-official。Adapter 不根据 URL 域名或模型名前缀猜测服务身份，也不存在可靠的“这是 DeepSeek”本地判定。缺少 base_url 或 model_name 时在创建模型请求前失败；其余配置按 DeepSeek wire contract 发出。官方端点、兼容代理或私有网关是否接受请求，以真实握手和模型响应为准。api_key 是否允许为空取决于端点，但空值不能被偷偷替换成其他账户凭据。

每个新 Runtime 捕获一次连接配置。用户修改 MW 模型设置后：

- 尚未启动的新 Conversation 使用新配置。
- 已 offline 的 Conversation 下次冷恢复使用新配置。
- 正在运行或 idle 的热 Runtime 不在进程内替换密钥；下一 Turn 前发现配置版本变化时，先优雅关闭热 Runtime，再以原 Conversation 和新配置冷恢复。

这样可以避免一段 Conversation 的同一进程在请求中途切换账户或端点。

### 8.5 DshRuntimePackageManager

DshRuntimePackageManager 是 DSH受管 SDK资源的唯一安装与解析入口。Adapter不得调用网络、pip、npm、npx或系统 PATH临时寻找 DSH，也不得把解压逻辑塞进 Supervisor。

PackageManager 负责：

- 根据 MW版本、Windows架构和兼容清单解析唯一允许的 Runtime版本。
- 向设置页和首次使用确认框提供名称、版本、来源、内置包大小、安装大小、状态、解压进度和错误摘要。
- 把解压写入专用临时目录并响应取消；未完成目录不得成为可启动版本。
- 在解压前后校验 EXE内置清单、SHA-256、文件列表、平台、架构、协议版本和发布者签名。
- 把完整 SDK原子安装到受管的 `sdk`目录，完成无模型、无凭据的本地自检后才发布安装校验记录。
- 支持修复、取消安装和卸载；有活动 Runtime时不得替换或删除 SDK。
- 将 Runtime会话数据与可删除的 SDK安装目录分离，卸载 Runtime不得删除 Conversation历史。

后端以正式 `DshRuntimePackageManager` Service作为状态权威，并通过设置 API提供只读状态、安装、取消、修复和卸载操作；安装任务由应用生命周期统一关闭。前端在现有 StorageSettingsSection中新增独立的 `SdkManagement`组件，消费真实 API状态和进度，不自行推断文件存在性，也不使用前端假数据。组件安装或卸载成功后必须刷新存储路径、运行时总量和受管资源分布。

资源状态至少包括 missing、verifying、extracting、installing、ready、failed、repairing和uninstalling。同一平台版本同时最多一个安装任务；并发首次使用请求复用同一任务，不重复解压。安装失败只返回 DSH_RUNTIME_NOT_INSTALLED或 DSH_RUNTIME_INSTALL_FAILED，不影响 MW其他业务能力。

Python SDK客户端随 MW主程序发布；Windows Runtime ZIP也在主 EXE内，但只有首次使用时才解压到可写运行目录。设置页可以把整项资源称为“DeepSeek Harness SDK”，但详情必须区分内置 ZIP大小与解压后的真实磁盘占用。

### 8.6 DshRuntimeSupervisor

Supervisor 是所有 DSH Runtime 和后代进程的唯一生命周期责任方。一个 Conversation 最多登记一个 RuntimeHandle。

Supervisor 负责：

- 只使用 PackageManager验证为 ready的固定 Windows Runtime可执行文件启动进程；不依赖系统 Node。首次使用可以先同步等待同一 PackageManager完成内置 ZIP安装，再启动进程。
- 构造白名单环境，而不是复制 AgentService 的完整环境。
- 通过 Windows 原生 launcher 以挂起状态创建进程，在任何 Node 代码执行前将其纳入 Job Object，再恢复主线程。
- 保存 stdin、stdout、stderr、PID、Job Object、启动时间和退出状态。
- 监控握手超时、无事件超时、异常退出和协议关闭。
- 在 Runtime 空闲时保留热进程。
- 根据空闲回收、容量限制、显式停止和应用关闭执行退出阶梯。
- 等待 Job Object 中的完整进程树消失后才报告回收完成。

官方 Python SDK客户端当前自行创建 Popen 并复制父环境，不能直接证明满足上述要求。MW主程序携带固定版本客户端和最小、可审计的生命周期补丁，使 SDK接受由 Supervisor提供的 process factory和显式环境。Windows process factory由一个窄原生 launcher实现，返回 SDK所需的管道和进程句柄，但不把进程树所有权交给 SDK。补丁身份、launcher版本、补丁哈希、上游提交和受管 Runtime资源版本一并进入 manifest。

### 8.7 DshSessionProtocol

MW 固定版 Runtime 在上游 JSON-RPC Server 之上增加两个窄方法：session/open 与 session/flush。它们只补足持续 Conversation 所需的生命周期，不提供 MW 工具调用，也不改变 DSH Agent Loop。

固定 wire contract 如下。所有 ID 使用小写规范 UUID文本；durableSeq 是目标 DSH Session 自身事件流中的最后持久序号，无事件时为 -1，不是全局序号，也不是 MW Turn序号。

| 方法 | 请求字段 | 成功响应 | 稳定错误 |
| --- | --- | --- | --- |
| initialize | 上游字段不变 | serverInfo 加 capabilities: mw-session-open-v1、mw-session-flush-v1 | DSH_PROTOCOL_INCOMPATIBLE |
| session/open | sessionId | sessionId、disposition: created、resumed或already-open、durableSeq | SESSION_NOT_FOUND、SESSION_CORRUPT、SESSION_VERSION_UNSUPPORTED |
| session/flush | sessionId | sessionId、durableSeq | SESSION_NOT_OPEN、SESSION_FLUSH_FAILED |
| session/prompt | 上游 sessionId、contentBlocks | 上游 messageId | 上游错误不变 |

session/open 接收由 MW 生成的稳定 dsh_session_id，并在 Runtime 内执行唯一判定：

- 持久化存储中没有该 ID：使用该精确 ID创建新 Agent 和 Session，返回 created。
- 持久化存储中已有该 ID：通过 DSH 的 sessionPersistence.prepare 和 agents.resume 恢复，返回 resumed。
- 同一 Runtime 内该 ID 已经存活：返回现有实例和 already-open，不重复创建。该结果只用于同一 runtime_generation 中 open响应丢失后的安全重试；新建流程不能把 already-open 当作 created，冷恢复流程也不能把它当作 resumed。
- 存储损坏、版本不支持或恢复失败：返回协议错误，绝不创建同名空会话掩盖失败。

上游 Server 当前在第一次 session/prompt 时调用 agents.create；仅重复传入同名 ID 并不会从磁盘恢复。因此 MW 发行补丁必须把“先 open，再 prompt”设为强制顺序，禁止依赖原有隐式创建路径。补丁和协议字段随 manifest 固定并接受协议测试。

session/flush 接收 dsh_session_id，等待 sessions.flush 完成，并返回已提交的最后事件序号。每个 Turn 在向 MW 结算前都必须 flush；正常 shutdown 也必须先 flush 所有已打开 Session。只有收到 flush 成功响应后，Registry 才能把该 Turn 标记为可冷恢复。

每条 session.event 通知携带 DSH SessionEvent 自身的 seq。EventMapper 在看到当前 Turn 的 turn/end 时保存 turn_end_seq；session/flush 返回的 durableSeq 必须大于等于 turn_end_seq，才能证明该 Turn 已落盘。Turn结算事务同时写入 Turn结果、turn_end_seq和Conversation.last_durable_seq，数据库提交才是 MW 发布 completed 的时点。

冷恢复时 session/open 返回 durableSeq，Adapter 按唯一规则与 Registry.last_durable_seq 对账：两者相等表示没有漏记；磁盘大于数据库表示上次 flush 后 MW 在提交事务前崩溃，Adapter读取并折叠缺失区间，补记已闭合 Turn或将未闭合 Turn记为 outcome_unknown，再原子推进数据库水位；磁盘小于数据库表示持久数据回退或丢失，Conversation进入 failed并报告 DSH_SESSION_DATA_LOST。任何分支都不得把水位差简单解释为新空会话。

MW turn_id 是本地数据库中的 UUID，与 DSH messageId 和 DSH turn序号分别存储，三者不得混用。提交 session/prompt 前，MW 先持久化 Turn为 created；收到 messageId 后在同一更新中写入 messageId并转为 running。若进程在请求已写入管道但响应尚未落库时崩溃，该 Turn进入 outcome_unknown，Adapter绝不自动重发。冷恢复先检查 DSH日志：能找到对应用户消息和后续 turn/end时据此结算；无法唯一关联时向父 Agent报告结果未知，并要求在同一 Conversation 中先检查工作区再决定后续操作。该策略选择“可能要求人工确认”，而不是冒险重复修改代码。

session_root 不通过 JSON-RPC 临时选择。Supervisor 在进程启动前把该 Conversation 的绝对 sessions 目录作为 DSH_SESSION_ROOT 注入 Runtime；session/open 只在这个固定存储内查找 dsh_session_id。MW 生成 ID、数据库记录、目录归属和 Runtime 环境四者必须一致。

### 8.8 DshEventMapper

EventMapper 顺序消费 DSH 通知，不重新排序，也不从 stderr 猜测正常协议事件。

主要映射为：

| DSH 事实 | MW 事实 |
| --- | --- |
| initialize 成功 | runtime_ready |
| session.status 进入 active | Turn running |
| assistant/chunk 文本增量 | output_delta |
| tool/call | tool_started |
| tool/result | tool_finished |
| assistant/message | 本轮候选最终消息 |
| turn/end | 本轮模型结束原因 |
| session.status 回到 idle | Turn 可以结算 |
| Runtime 退出但 Conversation 可恢复 | Child Agent offline |
| Runtime 或协议不可恢复 | Child Agent failed |

session/prompt 返回的 message_id 只代表消息已入队，不能被当作最终回答 ID。一次 Turn 的完成条件必须同时满足：属于当前 root session、已经观察到该轮活动、已经观察到 turn/end、session.status 回到 idle，并且 session/flush 已确认该 turn/end 落盘。最终文本从该轮最后一条有效 assistant/message 折叠；流式 chunk 只用于界面展示，不能替代最终消息。

## 9. DSH Runtime 发行组合

MW 使用自己的只读 Cordis 配置，不使用 DSH 默认 profile，也不读取用户目录中的 DSH 配置。

MW 使用同一份受管 `config/mw.patch.yml`组合，通过 Adapter注入当前 Turn的有效权限模式，决定沙箱策略和可见工具。模型不能选择配置文件或提高权限。

受管组合包含：

- JSON-RPC stdio Server。
- 仅监听 `127.0.0.1` 且使用系统分配动态端口的 DSH Web Server。
- DSH Web前端、Session投影、轨迹、工具调用、命令输出、diff和产物展示组件。
- MW托管 Session只读策略和 Web API方法白名单。
- Agent Core、Agent Loop、会话和上下文压缩组件。
- deepseek-official 模型适配器。
- DSH 本地子进程管理器。
- DSH 沙箱策略服务。
- Windows 沙箱 provider。
- fs-sandbox、文件观察策略和文本、图片读取工具；写入与编辑工具仅在可写模式注册。
- pwsh-sandbox能力；PowerShell工具是否暴露由下述模式组合决定。
- 受控的会话持久化与 checkpoint 组件。
- 运行统计和必要诊断组件。

运行组合明确排除：

- DSH TUI 和控制台 UI。
- Web端的 Prompt发送、Turn取消、交互响应、Session创建/删除、模型与凭据设置、权限修改、工作区切换、Agent Preset和插件管理能力。
- Codex 与 Claude Code provider。
- DSH subagent service、spawn/fork provider 和所有 subagent 工具。
- MW Tool Bridge。
- MCP Client 与任何 MCP Server。
- 用户插件目录与自动插件发现。
- DSH自身的插件市场、插件自动下载和上游自动更新；MW只允许 PackageManager解压 EXE内置 Runtime。
- 交互式审批工具和运行时权限提升入口。

DSH 的文件和 PowerShell 工具是其代码能力的一部分，不属于 MW 工具。它们直接在 DSH Runtime 内执行，并受 DSH 沙箱策略和 Supervisor 进程边界控制。

Windows发行物由固定 DSH提交的生产 deploy闭包生成，而不是由 MW重写 SDK或 Agent Loop。构建产物至少包含独立 Node 24、无 symlink的 DSH Node闭包、固定 ripgrep与原生依赖、JSON-RPC与 Web所需插件和前端资源。构建后必须在未安装系统 Node、DSH、WSL或 Docker的干净 Windows环境执行真实代码任务，证明 Runtime能够独立完成跨文件修改、PowerShell、测试失败诊断、修复和复测；Git能力在宿主已安装 Git时验收，缺少 Git不得影响非 Git代码任务。

模式组合的工具面固定为：

| 组合 | DSH文件工具 | 搜索 | PowerShell |
| --- | --- | --- | --- |
| readonly | 仅read/read_image；不注册write/edit | 不提供 | 不注册tool-pwsh，模型不能提交任意命令 |
| sandbox | read/read_image/write/edit，写入受workspace-write限制 | 通过pwsh | 注册tool-pwsh，经pwsh-sandbox的workspace-write执行 |
| full_access | read/read_image/write/edit | 通过pwsh | 注册tool-pwsh，经danger-full-access执行 |

readonly 不提供 Shell、目录枚举或搜索。命令、目录枚举、搜索、Git和测试统一通过可写模式的 `pwsh`执行，没有独立的 search/git/test工具。Adapter以 `session/open`返回的真实工具目录建立能力合同和提示词；主 Agent收到能力缺失时，应在相应授权下改派 sandbox DSH，不得把未执行的步骤报告为完成。

### 9.1 同一 Runtime 的只读 DSH Web

用户在“环境与变更”的子 Agent栏点击 DSH子任务时，MW展开右侧内置浏览器，访问该 Runtime公布的本地 Web地址并定位到当前 dsh_session_id。explore、coding子任务仍打开原有子 Agent对话侧栏。不得为观察另启第二个 `dsh web`进程，也不得让两个 Runtime共享同一 session_root。浏览器看到的实时轨迹必须来自正在被 Supervisor管理的同一个 Agent和 Session。

只读必须由 Host API强制，不得只隐藏输入框。MW托管 Session只允许 Web调用会话描述、历史分页、实时事件订阅、投影、工具展示和产物读取方法；所有能够创建或改变 Agent、Session、Turn、队列、交互、配置、权限、凭据、工作区和插件的调用都返回稳定只读错误。Web前端同时移除相应入口，避免向用户展示必然失败的操作。

每个 Runtime生成不可预测的临时访问凭据，Web Server只绑定 loopback动态端口。MW通过 URL片段传递临时 Web凭据和目标 Session标识；凭据只授权该 Conversation，不得列举其他用户或其他 Child Agent会话。URL、请求日志和浏览器内容不得包含 DeepSeek API Key、MW业务凭据或完整进程环境。

内置浏览器对 DSH使用按 loopback origin隔离的内存 Session并禁用缓存，普通网页继续使用原有浏览器 Session。真实导航 URL在内存中保留认证片段，地址栏、标题和错误信息脱敏；刷新、前进和后退继续使用原生认证状态。临时 Web凭据与 DSH页面缓存不得写入普通浏览器的持久 Session。

打开 Web不创建 Turn、不改变权限、不延长正在执行 Turn的超时，也不把 DSH变成 MW主 Agent。Runtime在线时直接打开；Conversation为 offline时，MW可以通过正常租约与冷恢复路径启动同一 Runtime、执行 session/open但不发送 session/prompt，然后开放历史页面。页面关闭不停止 Runtime；其后仍按普通 idle回收策略处理。

## 10. 权限继承设计

### 10.1 模式映射

MW 与 DSH 使用不同名称表达同一层级，Adapter 采用固定映射：

| MW 模式 | DSH 模式 | 行为 |
| --- | --- | --- |
| readonly | read-only | 仅提供read/read_image供文本与图片分析；不注册写入、编辑、搜索或PowerShell工具 |
| sandbox | workspace-write | 可以修改当前工作区和 DSH 私有临时目录；其他位置的写入被拒绝 |
| full_access | danger-full-access | DSH 文件沙箱不限制文件修改，仍受当前 Windows 用户权限约束 |

ChildAgentManager 先执行父子权限等级检查，Adapter 再完成名称映射。任何未知值都失败关闭，不能静默降级或升级。

### 10.2 权限何时确定

每个 Turn 开始前，Adapter 读取父 Agent当前有效模式，并与 Child Agent合同允许的上限取较低者。已经开始的 Turn 使用启动时捕获的模式，不在命令执行中途切换。

如果下一 Turn 的有效模式与热 Runtime 当前模式不同，Supervisor 先关闭热 Runtime，再使用同一 dsh_session_id 和 session_root 按新模式冷恢复。这样既保留 Conversation，又避免一个进程在运行期间改变安全边界。

权限提高只能来自用户或父 Agent已有的显式模式变化。DSH 的工具 schema 不提供 sandbox_permissions 升权入口，DSH 也不能通过追问要求 Adapter自动提高模式。

### 10.3 Windows 沙箱边界

沙盒和只读模式使用 DSH 的 fs-sandbox、sandbox-policy 和 Windows ACL 沙箱 provider；sandbox 额外通过 pwsh-sandbox执行命令，full_access 则明确绕过文件写入限制。readonly 不暴露任意PowerShell，因此需要 Git查询、编译或测试的任务必须由父 Agent在 sandbox 或 full_access 模式创建/继续该 Child Agent，不能由 DSH 自行升权。

这些模式是 DSH 当前提供的文件访问模式，不是完整主机安全域。它们不限制网络访问、注册表读取、IPC、进程启动或所有非文件副作用。MW 禁止加载 Codex/Claude provider和 MW连接插件，但如果宿主已经安装相关程序，PowerShell在技术上仍可能直接启动它们；系统提示中的“不要启动”是行为约束，不是内核隔离保证。产品若要求禁止网络、注册表或特定可执行文件，必须增加对应的 OS策略或 DSH pre-execute强制层，不能把文件沙箱当作已经实现。

DSH Session 持久化由 Runtime 主进程写入 Adapter 分配的 session_root，不经过模型可见的 fs/pwsh 工具沙箱。模型工具在 workspace-write 中只获得工作区和 DSH 为该会话分配的工具临时目录；session_root 不作为模型可写根公开。内部持久化权限和模型工具权限必须在测试中分别验证。

必须如实记录上游限制：Windows ACL runner 当前主要限制写入，不能阻止受限进程读取当前 Windows 用户本来有权读取的所有文件。只读和沙盒模式因此不是保密读取边界。MW 不得在界面或文档中把它描述为“DSH 无法读取工作区外文件”。如果产品将来要求读取隔离，必须引入能够强制读取边界的执行环境并重新完成设计评审。

## 11. 持续 Conversation 设计

### 11.1 创建

父 Agent第一次委派代码任务时，ChildAgentManager 创建稳定 child_id，Registry 在同一数据库事务中生成 dsh_session_id、分配 session_root 并写入 Conversation 记录。Supervisor 使用该 session_root 启动 Runtime并完成 initialize，Executor 随后调用 session/open；只有得到 created 后才发送第一条 session/prompt。

第一条 prompt 包含目标、工作区事实、权限事实、输入引用的可访问位置和输出要求。它不复制整个父对话；父 Agent负责把完成任务所需的上下文写成独立指令。

### 11.2 中大型任务优先使用同一 Conversation

MW 给父 Agent的子 Agent使用说明必须明确：

- 小型、边界明确且一次即可验证的修改可以在一个 Turn 完成。
- 中大型代码改动应保持同一个 child_id，不要为“分析”“修改”“测试”“修复测试”分别创建新的 DSH。
- 第一个 Turn 应让 DSH理解目标并尽可能完成修改和验证闭环。
- 如果 DSH 报告测试失败、遗漏或需要进一步信息，父 Agent应向同一 child_id 发送后续指令。
- 只有任务彼此独立、工作区不同、需要真实并行或原 Conversation 已损坏时，才创建新的 DSH 子 Agent。

DSH 的系统提示同时要求：对中大型改动，在当前 Conversation 中持续维护对仓库、方案、已改文件和测试结果的认识；不要在仍能继续修复时把中间状态包装成最终完成；最终回答必须明确列出实际修改、实际运行的验证和未解决事项。

“尽量使用同一 Conversation”是父 Agent的编排规则，不是让 DSH 在后台无限自问自答。每个 Turn 仍应尽可能完成当前指令；Turn 返回后，由父 Agent根据原始验收要求、DSH 最终说明以及 EventMapper观察到的真实测试命令和退出码决定下一步：要求已满足且验证通过时结束任务；存在测试失败、明确遗漏或可继续修复的问题时向同一 child_id 追问；缺少用户决定、凭据或外部条件时向用户报告阻塞。父 Agent不得只凭一段“已完成”文本忽略失败的 tool/result。

Turn 结果应包含最终文本以及由 MW 从事件流派生的验证摘要：实际变更文件、实际运行命令、退出码、是否仍有失败和 DSH 的结束原因。该摘要不是让 DSH 调用 MW 工具，而是 EventMapper 对已经发生的 DSH tool事件进行折叠。output_contract 可以进一步约束业务输出，但不是持续 Conversation 的前提。

### 11.3 追问

父 Agent对已有 child_id 发送追问时，Registry 先检查该 Conversation 没有活动 Turn。

- Runtime 为 idle：立即开始下一 Turn。
- Runtime 为 running：返回 DSH_CONVERSATION_BUSY，父 Agent等待该 Child Agent回到 idle 后再提交。
- Runtime 为 offline：先冷恢复，再执行。
- Runtime 为 stopped 或不可恢复 failed：拒绝追问并返回稳定错误。

同一 Conversation 不并行执行两个 Turn，也不在 MW 内部代为缓存未提交的追问，避免对话顺序、崩溃重发和工作区写入互相覆盖。

### 11.4 一轮完成后不关闭进程

Turn 结算并向父 Agent交付结果后，Child Agent进入 idle。Runtime、DSH Session 和进程管道继续保留，以便低延迟追问。不得在 EventMapper 看到 assistant/message 或 turn/end 时自动调用 shutdown。

### 11.5 热驻留与冷恢复

Supervisor 使用两个资源配置：空闲回收时间和最大热 Runtime 数量。它们是部署资源参数，不改变 Conversation 是否存在。

达到空闲时间、超过容量、应用进入资源回收或用户手动释放热进程时，Supervisor 对 idle Runtime执行有序 shutdown。Registry 将 Child Agent标记为 offline，但保留会话记录。

后续追问到达时，Supervisor 使用固定 Runtime、原 session_root、原 dsh_session_id、当前 DeepSeek 配置和当前权限模式重新启动。握手后 Executor 调用 session/open，并要求返回 resumed 及与 Registry 一致的最后事件序号；返回 created、找不到会话或序号倒退都视为恢复失败。恢复成功后才发送新的 session/prompt。

### 11.6 停止与删除

“停止当前 Turn”“关闭 Child Agent”和“删除 Conversation”是不同操作：

- 停止当前 Turn：现有 DSH SDK协议没有逐 Turn cancel。MW 请求 Runtime shutdown，并在宽限期后终止整个 Job Object；该 Turn 记为 stopped，Conversation 保留为 offline，可在恢复后继续。
- 关闭 Child Agent：终止 Runtime并把 Conversation 标记为 stopped，拒绝后续追问，但保留历史供查看。
- 删除 Conversation：在确认没有活动 Runtime后删除 MW 正式记录和对应 DSH 会话目录；这是独立的显式数据操作。

异常退出后的会话日志可能包含未闭合 Turn。冷恢复必须依赖固定版 DSH 的日志恢复规则，将未完成部分标记为 interrupted，而不能伪装成完成。

### 11.7 状态迁移

Child Agent状态只允许以下迁移：

| 当前状态 | 事件 | 下一状态 |
| --- | --- | --- |
| created | 取得Runtime租约并开始启动 | starting |
| starting | initialize与session/open成功 | idle |
| starting | 可修复启动失败 | offline |
| starting | manifest、协议或持久数据不可恢复 | failed |
| idle | 队首Turn开始 | running |
| running | Turn落盘并结算 | idle |
| running | Runtime退出但会话可恢复 | offline |
| idle | 空闲或容量回收 | offline |
| offline | 冷恢复成功 | idle |
| created、idle、running、offline | 明确关闭 | stopped |
| 任意非终态 | 确认不可恢复错误 | failed |

failed 和 stopped 都是终态；可恢复错误只能进入 offline，不能使用“可恢复 failed”这种混合语义。删除是数据生命周期操作，不是另一个运行状态。

Turn状态只允许以下迁移：

| 当前状态 | 事件 | 下一状态 |
| --- | --- | --- |
| created | session/prompt响应已记录 | running |
| created | 请求可能已写入但响应未记录 | outcome_unknown |
| running | turn/end、idle、flush与数据库结算成功 | completed、failed或stopped |
| running | Runtime在是否完成不明确时消失 | outcome_unknown |
| outcome_unknown | 冷恢复日志唯一证明已闭合Turn | completed、failed或stopped |
| outcome_unknown | 日志只能证明请求未完成 | failed或stopped |
| outcome_unknown | 日志无法唯一关联 | 保持outcome_unknown，等待父Agent检查工作区后确认 |

outcome_unknown 是可观察的非自动重试状态。它不会阻止 Conversation 冷恢复，但在父 Agent确认前不得把原 Turn宣称为成功，也不得原样重发输入。

每个状态发布以数据库事务为提交点。Runtime租约使用 child_id 唯一键、单调 runtime_generation、owner_instance_id、lease_expires_at和数据库版本执行比较并交换；只有持有当前 generation 的 Supervisor 可以更新运行状态或清除租约。进程内锁用于减少竞争，数据库唯一约束才是重启和多线程条件下的权威。

租约以数据库时钟为权威，每 5 秒续租一次，20 秒未续租才可进入接管检查。租约到期不直接授权启动新 Runtime：接管者必须先取得 Conversation数据库行锁，将 RuntimeLease.status 改为 reclaiming，打开并终止旧命名 Job，证明旧进程树已经消失，再以比较并交换写入更大的 runtime_generation。reclaiming 只属于 RuntimeLease内部状态，不是 Child Agent状态；对外 Child Agent保持 offline。无法证明旧 Job消失时租约保持 reclaiming并返回 DSH_RUNTIME_OWNERSHIP_UNCERTAIN，绝不启动第二个 Runtime。旧 owner 即使恢复，也会因 generation fencing失去写状态权限；旧 Job已在新 owner启动前终止，因此也不能继续写工作区。

Conversation 为 running 时追问统一返回 DSH_CONVERSATION_BUSY。MW 不承诺存储和恢复尚未交给 DSH 的追问队列；父 Agent或用户在看到 idle 后重新发起，这一行为必须在调用界面中明确呈现。

## 12. JSON-RPC 交互

### 12.1 启动握手

Adapter 通过 SDK向 Runtime发送 initialize，参数包含：

- 绝对工作区路径。
- 固定 provider：deepseek-official。
- 当前 model_name。
- 可选输出 token 上限。

Runtime 必须返回预期 serverInfo，并声明 MW 固定协议中的 session/open 与 session/flush 能力。名称、协议版本或必需能力不匹配时，Adapter 立即关闭进程并报告 DSH_PROTOCOL_INCOMPATIBLE。

initialize 之后必须先执行 session/open。新 Conversation 首次 open只接受 created；冷恢复首次 open只接受 resumed；同一 runtime_generation 因响应丢失重试 open时才接受 already-open。Adapter 将返回的最后事件序号按前述三分支与数据库水位对账，禁止将空会话误认成恢复成功。

### 12.2 提交消息

每轮通过 session/prompt 向已经 open 的稳定 dsh_session_id 提交文本内容。返回 message_id 后只表示入队成功。Executor 随后通过订阅事件判断 Turn 的真实开始和结束。

父 Agent的后续消息同样走 session/prompt，不创建新 DSH Session。Adapter 只在 Conversation 为 idle时接受请求；running时返回 DSH_CONVERSATION_BUSY，因此不依赖 DSH 对并发 prompt 的隐式行为，也没有崩溃后需要重放的 MW内置追问队列。

### 12.3 通知与结果

Adapter 订阅 root session 的 session.event 和 session.status。由于 MW 禁止 DSH 内部子 Agent，正常运行不应出现 subagent.started 或 subagent.finished；出现时视为发行配置或协议违反，记录诊断并终止 Runtime。

最终结果必须来自已闭合 Turn 的 assistant/message。看到 idle 后，Adapter 先调用 session/flush；只有持久序号覆盖本轮 turn/end 才结算。output_contract 是 MW 的交付约束，Adapter 在 DSH 结果返回后校验；不符合时该 Turn 失败，并保留经过截断和脱敏的诊断摘要。

### 12.4 关闭

正常回收先 flush 已打开 Session，再发送 shutdown 并等待有界时间。若 Runtime未退出，则关闭 stdin并进入 Job Object 终止流程。只有整个进程树退出、输出管道排空并完成状态落库后，Supervisor 才能报告关闭完成。强制退出前未完成 flush 的 Conversation 仍可尝试恢复，但 Registry 必须标记 needs_recovery，不能宣称最后事件已经持久化。

## 13. DeepSeek 配置与凭据

用户在 MW 中维护一份大模型配置。Adapter 不增加 DSH 独立设置页面。

| MW 配置 | DSH 使用方式 |
| --- | --- |
| api_key | DEEPSEEK_API_KEY 环境变量 |
| base_url | DEEPSEEK_BASE_URL 环境变量 |
| model_name | initialize 的 model 参数 |

API Key 只进入目标 DSH Runtime 主进程的白名单环境，不进入命令行、Cordis 文件、prompt、MW 事件、DSH 会话日志、错误文本、指标或诊断包。

Runtime 主进程需要读取 Key 来调用模型，但模型控制的 PowerShell、Git、测试和编译器进程不得继承它。MW 发行组合必须保留 DSH subprocess 的统一环境清洗：所有名称匹配 KEY、PASSWORD、SECRET、TOKEN 的变量以及全部 DSH_ 前缀变量都从子进程环境移除，随后只合并工具调用明确允许的普通环境。PowerShell执行器不得把 DEEPSEEK_API_KEY 作为显式 env 或 dshEnv 重新加入。发行配置也不得加载能在 Runtime 主进程内直接执行任意 JavaScript 或读取 process.env 的模型工具。

因此，DSH 模型执行普通环境枚举命令时，工具子进程环境中不应出现 DEEPSEEK_API_KEY。验收必须让真实 DSH 分别运行 PowerShell、Python、Node和测试子进程枚举环境，并断言 Key、Token及 DSH内部变量没有通过环境继承进入 stdout、stderr、tool/result、session.event和持久会话。

这不是同一 Windows 用户下的进程机密隔离。Runtime主进程内存中仍然持有 Key，而当前 DSH Windows文件沙箱不限制进程检查、调试或 IPC；拥有相应本机权限的恶意子进程理论上可能检查父进程。本文只承诺最小环境和不经正常工具环境传播，不承诺抵抗同用户主动进程攻击。若产品需要该保证，模型请求必须迁移到不同安全主体的本地凭据代理，DSH Runtime只持有短期、限域且不能换取原始 Key的句柄；在此之前，界面和安全文档必须披露这一边界。

Runtime 主进程环境只保留运行必需变量，包括 Windows 系统路径、受管 Runtime路径、工作区、DSH 会话根、临时目录和显式 DeepSeek 配置。不得以 os.environ.copy 的方式继承 AgentService 完整环境。Runtime 再创建工具子进程时必须进行第二次 DSH 环境清洗；“Supervisor 已使用白名单”不能替代这一层。

日志可以记录：是否存在 Key、端点主机、模型名、配置来源和配置版本。日志不得记录 Key、Authorization、完整 URL 查询参数或完整环境。

## 14. 工作区与文件数据

工作区由父任务明确绑定的项目目录或 MW 当前受控项目目录解析。Adapter 在创建 Conversation 时保存规范化绝对路径，DSH 输入不能覆盖它。

每个 Conversation 使用独立目录，例如：

~~~text
runtime/dsh/conversations/<child_id>/
├── sessions/        DSH 持久会话
├── temp/            DSH 私有临时目录
├── diagnostics/     有界、脱敏的故障材料
└── runtime.lock     当前 Runtime owner 信息
~~~

目录只是 DSH 执行数据。Child Agent身份、状态、父子关系和恢复元数据必须持久化到 MW 数据库。runtime.lock 只能用于本机崩溃检测，不能充当业务数据库。

沙盒模式允许修改工作区和 DSH 私有临时目录。会话目录不得放在被 DSH 当作代码仓库扫描的工作区内部，避免日志、密钥存在性信息或运行元数据进入 Git。

## 15. 进程与资源管理

### 15.1 一 Conversation 一 Runtime

同一 Conversation 同时最多一个 Runtime；不同 Conversation 可以拥有独立 Runtime并行工作。该规则使取消、stderr、资源统计和进程树都能准确归属。

### 15.2 Windows Job Object

Supervisor 为每个 Conversation 创建带稳定名称的专用 Job Object，并设置 JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE。Windows launcher 使用 STARTUPINFOEX 的 PROC_THREAD_ATTRIBUTE_JOB_LIST，在 CreateProcessW 创建 Node 的同一个内核操作中把进程加入该 Job，并同时使用 CREATE_SUSPENDED；完成管道和监督句柄登记后再恢复主线程。Job句柄和监督句柄全部设为不可继承，只有明确的 stdio管道句柄进入 Runtime。这样既不存在 Node 抢先启动后代的竞态，也不存在“进程已创建但尚未来得及 Assign时宿主崩溃”留下的挂起孤儿。普通 Popen 后再补 Assign 的实现不符合本文要求。

Job 不允许 breakaway。MW 支持的 Windows版本必须验证嵌套 Job行为；如果 AgentService 已经位于不允许嵌套的外层 Job，启动应以 DSH_SANDBOX_UNAVAILABLE 或 DSH_START_FAILED 失败，不能脱离外层限制运行。DSH 启动的 PowerShell、Git、测试、编译器和它们的后代都必须留在同一进程树责任范围内。关闭最后一个 Job句柄会触发兜底终止。

如果目标 Windows 环境无法证明后代进程被包含，发布构建失败，不能退化为只杀 Node 主进程。

Registry 在 CreateProcessW 之前先持久化 pending_launch generation和命名 Job；创建成功后再补写 PID、进程创建时间和 Runtime可执行文件哈希。MW 重启时先检查所有 pending_launch和非终态租约：能够 OpenJobObject 的命名 Job直接 TerminateJobObject并等待消失；Job 已不存在时，仅在 PID、创建时间和可执行文件路径全部匹配时处理残留，避免 PID复用误杀。完成清理后通过数据库比较并交换清除该 generation 的租约，再允许新 Runtime取得所有权。PROC_THREAD_ATTRIBUTE_JOB_LIST 是创建原子性的保证，JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE 是崩溃时的主要回收保证，启动对账是异常环境中的第二道保证。

### 15.3 退出阶梯

统一退出路径依次执行：

1. 停止接收新 Turn。
2. 尝试 JSON-RPC shutdown。
3. 关闭 stdin并等待协议退出。
4. 在宽限期后终止 Job Object 中的进程树。
5. 等待所有句柄和管道完成。
6. 更新 Registry 状态并释放锁。

正常完成、异常、超时、用户停止、配置变化、空闲回收和 MW 退出都复用这条路径。

### 15.4 容量管理

Supervisor 必须限制热 Runtime 数量。容量不足时只从 idle Runtime 中按最久未使用顺序回收；不得为了给新任务腾位置而杀死 running Runtime。

如果所有 Runtime 都在运行，新建或冷恢复请求返回 DSH_RUNTIME_CAPACITY，Child Agent保持 created或offline，由调用方稍后重试。本文不定义第二种容量排队状态，也不在内存中静默积压启动请求。

资源参数由 AgentConfig 提供服务级默认值，可以由正式用户设置覆盖；不得散落为 Supervisor 内部常量。规范默认值为：idle_timeout_seconds 600、max_live_runtimes 2、max_turns_per_conversation 32、default_turn_timeout_seconds 1800、shutdown_grace_seconds 5、startup_timeout_seconds 30、lease_renew_seconds 5和lease_expiry_seconds 20。所有值都必须是有界正数，且 lease_expiry_seconds 至少为 lease_renew_seconds 的三倍；测试可以注入更小值验证边界。

max_turns_per_conversation 是防止无人监督无限追问的运行上限。达到上限后 Conversation 保持 idle，父 Agent向用户说明并等待明确继续；用户继续后可以增加同一 Conversation 的预算，不创建新会话绕过限制。

Turn 的绝对超时来自 ChildAgentContract.timeout_seconds；没有提供时使用 default_turn_timeout_seconds。模型流的正常 chunk、工具事件和状态事件不延长绝对超时。握手只使用 startup_timeout_seconds；运行期“无事件”由固定版 DSH 模型适配器的 stream idle timeout处理，Supervisor 不再发明另一套会因长测试而误杀的滑动计时器。

运行中修改 idle_timeout_seconds 和容量参数只影响后续调度；不得终止 running Runtime。降低 max_live_runtimes 时，Supervisor 按最久未使用顺序逐个回收 idle Runtime，直到满足新上限。

## 16. 提示词设计

DSH 的系统提示应简洁说明其角色和硬边界：

- 你是 MW 的专用代码子 Agent。
- 只处理当前工作区中的代码分析、修改、测试和相关 Git检查。
- 使用 DSH 自己提供的文件、搜索和 PowerShell 工具。
- 不寻找或调用 MW 工具、MCP、外部子 Agent、Codex 或 Claude Code。
- 遵守当前 DSH 沙箱模式，不尝试升权。
- 修改前先理解相关代码，修改后运行与风险相称的测试。
- 中大型任务尽量在当前 Conversation 内完成完整闭环；测试失败时继续定位和修复，不把未验证实现声称为完成。
- 最终回答说明修改内容、验证命令、验证结果和仍未解决的问题。

父 Agent侧提示同时说明：后续修复和追问优先发送给原 child_id；不要因为一个 Turn 已经返回就认为 DSH Conversation 已关闭。

## 17. 错误模型

MW 对外使用稳定错误码，不依赖 DSH 原始错误文本：

| 错误码 | 含义 | Conversation 后续状态 |
| --- | --- | --- |
| DSH_CONFIG_MISSING | 缺少 DeepSeek URL或模型 | 保持 created/offline，可修复配置后重试 |
| DSH_RUNTIME_NOT_INSTALLED | 当前 MW兼容的 Windows Runtime尚未安装 | 保持 created/offline，用户安装后重试 |
| DSH_RUNTIME_INSTALL_FAILED | 内置 Runtime签名、哈希、解压或自检失败 | 保持 created/offline，可修复或重试安装 |
| DSH_RUNTIME_INVALID | 文件、哈希、补丁或版本不匹配 | failed，禁止启动 |
| DSH_START_FAILED | Node、Runtime、Job Object或沙箱临时启动失败 | offline，可重试 |
| DSH_PROTOCOL_INCOMPATIBLE | 握手或协议版本不匹配 | failed |
| DSH_PROTOCOL_ERROR | 运行中的 JSON-RPC 数据违反固定协议 | offline，人工或升级后重试 |
| DSH_MODEL_AUTH_FAILED | DeepSeek 拒绝凭据 | offline，修改配置后重试 |
| DSH_MODEL_PROTOCOL_FAILED | base_url 不接受 deepseek-official 请求语义 | offline，修改配置后重试 |
| DSH_SANDBOX_UNAVAILABLE | 当前受限模式无法建立 DSH 沙箱 | offline，禁止无约束降级 |
| DSH_TURN_TIMEOUT | Turn 超时或长期无事件 | 当前 Turn stopped，Conversation offline |
| DSH_PROCESS_EXITED | Runtime 意外退出 | 当前 Turn failed，Conversation按日志可恢复性进入 offline 或 failed |
| DSH_OUTPUT_INVALID | 最终结果不符合 output_contract | 当前 Turn failed，Conversation仍可追问 |
| DSH_CONVERSATION_BUSY | Conversation已有活动Turn | Conversation状态不变，调用方等待idle后重试 |
| DSH_RUNTIME_CAPACITY | 热Runtime均在运行且已达容量 | Child Agent保持created/offline，调用方稍后重试 |
| DSH_RUNTIME_OWNERSHIP_UNCERTAIN | 无法证明旧Runtime进程树已退出 | Child Agent保持offline，内部租约保持reclaiming，禁止启动新Runtime |
| DSH_SESSION_DATA_LOST | 磁盘durableSeq小于数据库水位 | failed，禁止继续写入 |
| DSH_CONVERSATION_STOPPED | Conversation 已明确关闭 | 终止，不可追问 |
| DSH_WEB_READ_ONLY | Web请求试图改变 MW托管 Session | Conversation状态不变，拒绝请求 |

认证失败不自动重复请求。代码写入后发生的模型或进程错误也不自动重跑整个 Turn；父 Agent应先在同一 Conversation 中询问状态或要求检查工作区，避免重复修改。

## 18. 打包与部署

MW Windows 主 EXE携带 `agent_service/vendor/deepseek_harness/`中的固定 Python SDK客户端和以下 Runtime资源：

~~~text
resources/dsh/
├── upstream.json            锁定提交、Node主版本与兼容版本
├── patches/mw-runtime.patch MW协议、权限和只读Web补丁
├── config/mw.patch.yml      受管Cordis组合
└── sdk/
    ├── sdk.zip              固定文件名的Windows Runtime资源包
    └── sdk.manifest.json    版本、文件列表、大小与哈希清单
~~~

执行面压缩为固定的 Windows x64受管 SDK资源并进入主 EXE，按需安装后的布局为：

~~~text
<base_data_dir>/assets/sdks/dsh/
├── sdk/                         当前唯一安装的SDK
│   ├── node/node.exe
│   ├── runtime/node/            无symlink的DSH生产闭包与Web资源
│   ├── dsh-job-launcher.exe
│   ├── config/mw.patch.yml
│   ├── manifest.json
│   ├── LICENSE
│   └── THIRD_PARTY_NOTICES.md
├── work/                        自检临时目录，不可执行
└── current.json                 当前安装的兼容性校验记录
~~~

发布者运行 `scripts/build_dsh_sdk.bat`，从 `resources/dsh/upstream.json` 锁定的 DSH提交构建代码与 Web资源；构建入口在开始工作前必须比较 checkout的 `HEAD`与锁定提交，不一致立即失败。脚本生成无 symlink的生产 Node闭包，再加入锁定主版本的 Node、MW Job launcher、协议补丁、Cordis组合和只读 Web资源，完成校验后写入 `resources/dsh/sdk/sdk.zip`与 `sdk.manifest.json`。MW不自行重写 SDK或 Agent Loop。

Runtime SDK不在用户电脑构建。只有 DSH锁定提交、MW补丁、Cordis配置、内置 Node主版本或 Runtime版本发生变化时，发布者才重新运行一键脚本。普通 MW应用构建复用仓库中的固定 ZIP与 manifest；PyInstaller校验两者存在、版本一致且哈希正确后打入 EXE，任一条件不满足就中止构建。用户侧安装只是读取 EXE内置资源、校验和原子解压，不调用网络、npm、pnpm、Python或编译器。

当前 Windows x64 SDK实测为 66,222,943 bytes内置 ZIP、191,583,631 bytes解压后占用。该 ZIP直接嵌入 MW主 EXE，应用启动时不解压；设置页安装或首次 DSH任务才懒解压。DSH Web和动态 Node资源以受管多文件目录运行，默认安装位置为 `runtime/assets/sdks/dsh/sdk`。

首次使用和设置页安装都通过 DshRuntimePackageManager。正式客户端不访问网络，不执行 pip、npm或 npx，不下载源码，不访问插件市场，也不把解压后的受管资源写入 MW安装目录。内置清单必须声明精确压缩大小和安装大小；界面显示真实解压进度。原子安装完成前不得创建 DSH Runtime。

制品文件名和安装目录始终保持 `sdk`命名；manifest中的 `version`仅用于兼容性和升级校验。设置页显示清单大小与真实磁盘占用，不沿用旧 SDK的容量数字。

Runtime使用资源包内的固定 Node 24与物化 DSH闭包，不使用 Electron内置 Node，也不依赖 PATH中的 Node、DSH、Codex、Claude Code、WSL或 Docker。PowerShell执行器按固定版 DSH的 Windows解析规则选择 PowerShell 7或系统 Windows PowerShell，并必须通过真实 Windows测试。

Conversation会话目录不位于 SDK安装目录中。卸载或替换 Runtime不得删除会话；删除 Conversation也不得删除共享 Runtime。修复、升级或卸载前 PackageManager检查活动 Runtime和安装任务，无法安全操作时明确报告占用，不通过强杀绕过 Supervisor。

## 19. 版本与升级

内置 `sdk.manifest.json`以及安装目录中的 `manifest.json`记录兼容版本和资源校验信息：

- DSH 源码提交。
- Python SDK 源码提交。
- MW SDK生命周期补丁 ID和哈希。
- Cordis 配置版本和哈希。
- Windows Runtime版本、DSH生产闭包版本和内置 Node版本。
- Runtime、sidecar、Web资源和 Cordis组合的逐文件哈希。
- 内置 ZIP文件名、压缩大小、安装大小、签名和签名密钥 ID。
- 构建平台、架构和构建时间。
- 已验证的 JSON-RPC serverInfo 与协议基线。

Adapter 每次启动 Runtime 前通过 PackageManager校验组合。未安装时返回 DSH_RUNTIME_NOT_INSTALLED；缺文件、哈希不符、签名无效或版本组合未知时禁止运行并提供修复入口。

升级 DSH时更新固定的 `sdk.zip`与 `sdk.manifest.json`，必要时同时升级主程序中的 SDK客户端，重新审核 MW补丁并验证旧 Conversation的冷恢复。应用只保留当前一套 SDK：等待活动 Runtime全部退出，在临时目录完成校验和自检后，原子替换固定 `sdk`目录并清理旧安装；替换失败时保留原安装。若新 SDK无法安全读取旧会话，升级代码必须明确迁移或标记不可恢复，不能静默创建空会话冒充续接成功。

## 20. 安全边界

### 20.1 DSH 能访问什么

DSH 能访问当前工作区、自己的会话与临时目录、DeepSeek API，以及当前权限模式允许的本机文件和命令。它不拥有 MW 数据库连接、设置服务对象、密码库、用户业务数据 API或 MW 工具注册表。

### 20.2 DSH 不能做什么

MW 发行组合不注册内部子 Agent、Codex/Claude Code provider、用户插件或 MW工具连接，DSH 也不能请求 MW 替它执行工具或自行把受限模式改为完全访问。这是对已装载能力和控制面的保证；任意 PowerShell在当前 OS权限下还能启动哪些宿主程序，受上一节记录的操作系统边界约束。

DSH Web不是新的信任主体。它只通过 loopback和每 Runtime临时凭据访问当前 Conversation的只读投影，服务端拒绝全部写方法。任何网页脚本、其他本机进程或用户手工构造的请求都不能借 Web绕过 ChildAgentManager、权限映射、Turn串行或 Supervisor生命周期。

### 20.3 真实限制

DSH Runtime仍以当前 Windows 用户身份运行。full_access 明确拥有该用户的本机权限。Windows read-only/workspace-write 能强制限制主要写入路径，但当前上游 ACL provider不能构成完整读取隔离。此限制属于产品安全说明和验收报告的一部分，不能只留在开发注释中。

## 21. 测试策略

实现必须包含以下层级，而不是只用 Mock 证明接口可调用。

### 21.1 协议测试

- initialize 成功和版本拒绝。
- session/open 对新会话返回 created、对持久会话返回 resumed，且错误时不创建空会话。
- 同generation重复open返回already-open；新建和冷恢复流程不会错误接受该结果。
- session/flush 返回覆盖当前 turn/end 的持久序号。
- 冷恢复覆盖disk==registry、disk>registry补记和disk<registry失败三种水位分支。
- session/prompt 入队与完整事件顺序。
- assistant/chunk、tool/call、tool/result、assistant/message、turn/end 和 idle 映射。
- 一次 Turn 完成后 Runtime 仍然存活。
- 同一 session_id 的第二轮能够使用前一轮上下文。
- running Conversation 的第二条追问稳定返回 DSH_CONVERSATION_BUSY，idle 后可以重新提交。
- session/prompt响应落库前崩溃时 Turn进入outcome_unknown，系统不自动重发。
- outcome_unknown经日志对账可以结算或保持未知，任何分支都不会把原输入自动重发。
- 协议损坏、stdout 关闭和未知事件失败关闭。

### 21.2 Conversation 测试

- 小任务单 Turn 完成。
- 中大型任务在同一 Conversation 中完成分析、修改、测试失败、修复和复测。
- 父 Agent依据真实测试退出码而不是仅凭完成文案决定是否继续追问。
- 热 Runtime 追问。
- idle 回收后的冷恢复追问。
- MW 重启后的冷恢复。
- 当前 Turn 停止后恢复 Conversation。
- stopped Conversation 拒绝追问。

### 21.3 权限测试

- readonly 可以读取但不能修改工作区。
- readonly 的真实工具目录仅有read/read_image；write/edit、Shell、目录枚举和搜索均不提供。
- sandbox 可以修改工作区并运行测试。
- sandbox 不能写入工作区和允许临时目录之外的位置。
- full_access 按当前用户权限执行。
- 子 Agent请求的模式高于父 Agent时被拒绝。
- 父模式变化后，下一个 Turn 通过冷恢复使用新模式。
- 沙箱 provider 不可用时 fail closed，不退化为本地无约束执行器。
- Windows 读取隔离限制被单独记录，不编写虚假“工作区外不可读”断言。

### 21.4 进程测试

- 正常 shutdown 后无 Node、PowerShell、Git、pytest 或编译器残留。
- Node 通过 PROC_THREAD_ATTRIBUTE_JOB_LIST 在 CreateProcessW 时原子加入带 KILL_ON_JOB_CLOSE 的命名 Job，随后才恢复执行，Job句柄不可继承。
- Turn 超时后整个 Job Object 退出。
- Runtime 崩溃后后代进程被回收。
- MW 强制退出后的 Job close 回收与下次启动租约对账。
- 租约过期接管先终止旧命名 Job并证明退出，再写入新 generation和启动新 Runtime。
- 容量回收只选择 idle Runtime。
- 正在运行的测试进程不会因为另一 Conversation 启动而被错误终止。

### 21.5 SDK资源安装测试

- 未安装 Runtime时，首次创建 DSH子 Agent返回可安装状态，不启动残缺进程，也不影响其他 MW功能。
- 设置页展示固定版本、来源、内置包大小、安装大小、解压进度、磁盘占用、路径和失败原因。
- 同一版本的并发安装请求只产生一次解压；取消、失败重试和修复均不把临时目录标记为 ready。
- 内置清单、SHA-256、Windows x64平台、文件列表、协议版本或发布者签名任一不匹配都会失败关闭。
- 新 SDK先在临时目录安装和自检，再原子替换固定sdk目录并清理旧安装；替换失败保留原安装。
- 活动 Runtime或安装任务阻止替换与卸载；成功卸载 Runtime后 Conversation历史仍然存在。
- 安装与卸载后的存储统计和“SDK 与运行组件”管理状态与真实磁盘一致。

### 21.6 DSH Web观测测试

- 同一 Runtime同时完成 JSON-RPC握手和 Web启动，Web展示的 session_id、事件 seq和最终回答与 SDK观察一致。
- 用户从 MW打开当前 Child Agent后能看到实时 assistant、tool/call、tool/result、PowerShell输出、diff、测试结果、产物和 turn/end。
- 观察过程中系统中只有该 Conversation的一个 DSH Runtime，没有第二个 `dsh web`进程或第二个 Session writer。
- MW托管 Session的 Prompt、取消、交互响应、队列、创建/删除、设置、凭据、权限、工作区和插件写请求均由服务端返回 DSH_WEB_READ_ONLY。
- Web只能访问 URL凭据授权的当前 Conversation，不能列举或打开其他用户、其他父会话或其他 Child Agent的 Session。
- Web只监听 loopback动态端口；错误 URL、过期凭据、跨 Session凭据和非 loopback访问均被拒绝。
- 打开 Web不创建 Turn、不发送 Prompt、不改变权限；关闭页面不停止 Runtime。
- offline Conversation通过正常租约冷恢复后可以查看持久历史，但不会因为打开页面执行新一轮模型请求。
- Web页面、网络响应和日志不包含 DeepSeek API Key、MW凭据或完整 Runtime环境。

### 21.7 Windows发行物测试

- 从固定提交生成 DSH生产 Node闭包、独立 Node 24和 Windows Job launcher资源包。
- 未安装 Node、DSH、Codex、Claude Code、WSL 和 Docker的 Windows 机器可运行。
- 不依赖开发仓库 node_modules。
- manifest 篡改和缺文件会被拒绝。
- Windows Runtime在真实仓库完成跨文件读取、搜索、编辑、PowerShell、Git、测试失败、修复和复测。
- 同一发行物提供 SDK JSON-RPC与只读 DSH Web，不依赖另装 DSH独立版。
- API Key 不出现在命令行、日志、事件、会话文件和诊断包中。
- DSH 启动的 PowerShell、Python、Node和测试进程不会通过环境继承获得 DeepSeek Key或 DSH内部环境；同用户主动进程检查边界在安全说明中披露。
- 安装、升级和卸载后没有遗留进程与未登记运行目录。

## 22. 验收矩阵

| 需求 | 实现落点 | 验收证据 |
| --- | --- | --- |
| DSH 不使用 MW 工具 | Cordis 排除 Bridge、MCP和 MW 服务 | 工具目录快照与真实任务事件中只出现 DSH 工具 |
| 只使用 DeepSeek语义 | 固定 deepseek-official 和三项配置映射 | 官方 DeepSeek与允许的兼容网关真实请求；不加载其他模型适配器 |
| 修改代码并运行测试 | fs-sandbox、pwsh-sandbox和对应工具 | 真实仓库修改与测试任务 |
| Windows原生代码能力 | 固定 DSH生产 Node闭包、Node 24、Job launcher和 MW Cordis组合 | 干净 Windows机器上的跨文件修改、PowerShell、Git、失败修复与复测 |
| 中大型修改复用 Conversation | 稳定 child_id、session_id和追问接口 | 多轮修改—失败—修复—复测场景 |
| 回答后进程可驻留 | Turn 与 Runtime状态分离 | 第一轮 idle 后 PID仍存活，第二轮复用同 PID |
| 空闲后仍可继续 | session/open、session/flush与持久化冷恢复 | 回收 PID 后 session/open 返回 resumed，并用同 session_id 完成追问 |
| 权限继承父 Agent | 固定模式映射与每 Turn重解析 | 三模式真实 Windows 权限测试 |
| 子 Agent不能自行升权 | 无审批/升权工具，模式由 Adapter注入 | DSH 请求更高权限无法改变执行模式 |
| 无残留进程 | 挂起启动、命名 Job、KILL_ON_JOB_CLOSE、启动对账和统一退出阶梯 | 正常、超时、崩溃、强退、重启路径的进程树检查 |
| 用户无需手工安装 DSH/Node | PackageManager从 EXE内置 ZIP安装固定 Node 24与 DSH生产闭包 | 首次使用校验、解压、安装后在无网络的干净 Windows环境运行 |
| 缺少 SDK时禁止构建 | AgentService.spec强制校验固定 manifest、ZIP、大小和 SHA-256 | 删除或篡改任一制品后 PyInstaller立即失败 |
| 使用 DSH原生 Web观察 | 同一 Runtime装载 JSON-RPC和只读 Web，MW提供打开入口 | 实时轨迹一致性、单 Runtime检查和全写方法拒绝测试 |
| 开发版升级可控 | 固定提交、补丁和 manifest | 哈希拒绝、版本拒绝和升级冷恢复测试 |

## 23. 完成定义

只有以下事实全部成立，DSH Adapter 才算完成：

- 用户仅配置 MW 推荐的 DeepSeek API即可使用代码子 Agent。
- DSH 使用自己的代码工具，不依赖或接触任何 MW 工具。
- DSH 能完成真实的跨文件修改和测试闭环。
- Windows x64 Runtime由固定 DSH提交的生产闭包、独立 Node 24和 Job launcher组成，用户机器无需另装 Node或 DSH即可执行代码任务。
- Python SDK客户端和 Runtime ZIP随 MW主 EXE发布；Runtime可在“SDK 与运行组件”中按需解压、查看进度、校验、修复和卸载。
- 用户可以从 MW打开同一 Runtime提供的 DSH原生 Web查看轨迹；该 Web对 MW托管 Session服务端只读，不能成为第二控制面。
- 父 Agent能够对同一 child_id 连续追问，中大型任务不会被迫丢失上下文。
- Turn 完成、Runtime idle、Runtime offline 和 Conversation stopped 在状态与界面上不会混淆。
- 三种 MW 权限模式被准确映射并在真实 Windows 环境执行；已知读取限制被如实说明。
- 所有退出路径都能证明完整进程树已经消失。
- API Key 和 MW 私有服务不越过规定边界。
- Runtime、SDK客户端、补丁、内置 Node、Web资源和 Cordis配置都能由 manifest精确核对。
- 固定版真实 DSH、真实 DeepSeek API、真实文件修改和真实测试执行均通过验收。

## 24. 上游依据

实现评审必须逐项核对 manifest 中固定提交的下列源码，不得只引用 README 首页：

- packages/sdk/protocol/src/types.ts：正式 JSON-RPC 请求和通知集合。
- packages/sdk/server/src/server.ts：initialize、session/prompt、shutdown与事件通知；同时证明上游隐式 getOrCreateSession 使用 agents.create，不能代替本文要求的持久恢复。
- python/sdk/src/deepseek_harness/client.py：stdio客户端、反向请求队列、进程创建和关闭行为。
- python/sdk-runtime/platforms.json、scripts/build-exe-for-python-sdk.ts和对应 CI：Windows x64 Runtime、`win_amd64` wheel和单文件执行闭包的上游构建依据。
- packages/bundle/web-app、packages/host/webserver、packages/client与packages/api/remotes：DSH Web组合、浏览器连接、Session投影和所有必须被 MW只读策略限制的写方法。
- packages/core/agent-loop/src/index.ts：agents.create与agents.resume的会话所有权。
- packages/session/session-persistence/src/index.ts及 coordinator.ts：prepare、load、flush和未闭合 Turn修复规则。
- packages/subprocess/subprocess/src/index.ts：SENSITIVE_ENV_PATTERN、DSH_清洗和 scrubbedParentEnv。
- packages/fs/fs-sandbox与packages/shell/pwsh-sandbox：文件和PowerShell受限执行语义。
- packages/sandbox/sandbox-policy与sandbox-windows-acl：模式解析、Windows写入限制和读取边界。
- packages/session/session-persistence-jsonl：session_root布局、提交与恢复行为。

公开入口分别位于 [DeepSeek Harness仓库](https://github.com/deepseek-ai/deepseek-harness)、[Python SDK](https://github.com/deepseek-ai/deepseek-harness/tree/master/python/sdk) 和 [SDK Protocol](https://github.com/deepseek-ai/deepseek-harness/tree/master/packages/sdk)。链接用于导航，行为依据必须替换为 manifest 记录的确切提交内容。

MW 补丁必须单独列出上游没有提供的行为：session/open、session/flush、SDK process factory、Windows挂起 launcher和运行时能力声明。每个补丁都有自己的测试与哈希，不能把 MW 扩展描述成上游已有能力。

上游主分支的新文档不能自动改变已发布 MW 的行为。升级评审需要重新回答本文所有验收项，并在变更记录中列出上游差异和 MW 补丁是否仍然必要。
