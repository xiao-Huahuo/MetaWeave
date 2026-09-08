# 启动,构建与部署

## 启动

### 环境要求

* Python 3.12+
* Node.js 22.18，或 Node.js 24.12 及以上版本
* npm 10+
* 使用 Agent 时至少准备一种模型入口：OpenAI 兼容远程模型，或在客户端确认下载 CPU 本地 Qwen；模型缺失不影响基础服务启动

### 1. 配置模型

推荐直接在 Editor 客户端的设置页填写主模型与小模型的名称、API Key 和 OpenAI 兼容 API 地址。根目录 `.env` 只用于提供服务级默认值，例如 `AGENT_MODEL_NAME`、`AGENT_MODEL_API_KEY`、`AGENT_MODEL_BASE_URL` 和对应的 `AGENT_SMALL_MODEL_*`。

没有配置可用远程大模型时，Agent 会回退到 CPU 本地 Qwen；模型不存在时必须由用户在“设置 → 存储管理 → 模型管理”中确认下载。Embedding、ReRank、PaddleOCR 和本地 Qwen 都不在后端启动路径中自动下载，缺失模型不会阻止 API 和桌面窗口启动。

### 2. 启动后端（FastAPI）

```bash
# 安装后端依赖
python -m pip install -r agent_service/requirements.txt

# 启动服务（HTTP: 8002, gRPC: 50051）
python -m uvicorn main:app --host 127.0.0.1 --port 8002
```

`AgentConfig` 的默认 HTTP 监听地址仍是 `0.0.0.0`；开发机一般应像上面一样显式绑定 `127.0.0.1`，不要把无通用认证的开发服务直接暴露到不可信网络。gRPC 默认监听 `50051`，由 FastAPI lifespan 同步启动和关闭。

开发模式默认将项目目录下的 `resources/knowledge/` 作为知识库根目录，用户可在前端重新选择知识库。服务启动和切换知识库都不会自动重建全部索引；灌库由前端的全库、目录或单文件操作按需触发。启动时会执行 Alembic 数据库迁移，但不会下载或同步加载全部模型。

### 3. 启动前端（Electron + Vite + Vue 3）

```bash
cd editor
npm ci
npm run dev:electron
```

`dev:electron` 只会并行启动 Vite 和 Electron，不会启动 Python 后端。Vite 默认监听 `http://127.0.0.1:5173`，开发代理将 API 转发到 `http://127.0.0.1:8002`，因此应在另一个终端先启动后端。

`启动.bat` 会先按端口停止旧服务，等待后端 `/health` 返回 MetaWeave 的健康标识后再启动前端。Vite、开发代理与 Electron 共用 `FRONTEND_PORT`、`AGENT_HTTP_PORT` 派生出的地址；Electron 会等待 Vite 真正返回 HTTP 响应，旧的托盘实例收到二次启动事件时也会重新加载已经恢复的开发服务。DSH默认关闭且不会在启动脚本中解压；用户在基础设置开启 DSH后，前端壳层确认后端就绪并读取用户档案，再与模型初始化并行触发 DSH Runtime后台安装。

`npm ci` 会先替换整个 `node_modules`。Windows 下执行前必须在原终端用 `Ctrl+C` 停止 `dev:electron`，并从托盘退出 Electron；否则 Rolldown 等已加载的 `.node` 原生文件会因占用而报 `EPERM unlink`。不要用 `taskkill /IM node.exe /F`，它会误杀同机上的其他 Node 服务。

### 4. 验证

执行 `npm run dev:electron` 后 Electron 会自动打开桌面窗口。也可以在浏览器访问 `http://127.0.0.1:5173` 检查普通页面；目录选择、系统剪贴板、托盘、悬浮窗和内嵌 BrowserView 等能力必须在 Electron 中验证。

后端健康检查：

```bash
curl http://127.0.0.1:8002/health
```

### 5. 必要设置

1. 使用远程模型时，在 Editor 设置中配置模型名称、API Key 和 OpenAI 兼容 API 地址；不使用远程模型时，在模型管理中确认下载本地 Qwen。
2. Embedding、ReRank、PaddleOCR 和图片理解均按用户设置与实际业务入口启用，不要通过启动脚本预下载模型。
3. 如果需要联网搜索，在设置中配置当前网络可用的代理地址；无法访问搜索服务时，联网工具会失败，但不影响本地功能启动。

## 测试与质量检查

后端测试必须按文件串行执行，避免模型依赖、线程池和全局状态在单个 pytest 进程中持续累积：

```bash
# 单文件或单测试
python -m pytest tests/test_database_migrations.py -q

# 多文件完整回归：每个测试文件使用独立子进程
python -m tests.contracts.run_serial_pytest --output runtime/test-results/pytest.json
```

前端定向测试和完整串行回归：

```bash
cd editor
npm exec -- vitest run src/path/example.spec.ts --maxWorkers=1 --no-file-parallelism

cd ..
python -m tests.contracts.run_serial_vitest --output runtime/test-results/vitest.json
```

其他常用检查：

```bash
cd editor
npm run type-check
npm run lint
npm run test:e2e:smoke
```

`npm run lint` 当前带 `--fix`，会修改文件；先检查工作区，避免覆盖其他任务的并行改动。启动过的后端、Vite、Electron 和浏览器进程必须在验证结束后关闭，并复查使用的端口已经释放。

## 构建

### 一键生产 DSH Runtime SDK

DSH Runtime SDK不在用户电脑生产，也不需要上传到网络。发布者只在升级 DSH源码、MW补丁、Cordis配置、Node主版本或 Runtime版本时更新sdk.
#### 普通 MW构建

全新克隆的 MW仓库已经包含 `resources/dsh/sdk/` 中固定的 ZIP与 manifest。普通开发和 EXE构建直接使用这份成品，不需要另行克隆 DSH，也不需要为了 DSH安装 Node、pnpm或 C编译器。

#### 重新生产 SDK

只有升级 DSH、MW补丁、Cordis配置、Node主版本或 Runtime版本时才重新生产 SDK。构建机需要 Git、Node 24、pnpm以及 `cl.exe`或 `gcc.exe`。在 MetaWeave根目录执行：
```bat
scripts\build_dsh_sdk.bat
```

脚本读取 `resources/dsh/upstream.json`，自动克隆其中锁定的 DSH仓库，checkout到完整 commit `47f943859bef60e4160492346772ded9b24f765a`，应用 `resources/dsh/patches/mw-runtime.patch`，然后在临时目录构建。它不跟随 `master`、tag或本机已有分支，也不修改开发者现有的 DSH工作区。

无网络环境可以把本地 DSH仓库作为克隆来源；脚本仍会在临时目录 checkout锁定 commit并应用 MW补丁：

如果源码位于其他位置,传入路径：
```bat
scripts\build_dsh_sdk.bat D:\Projects\Python\deepseek-harness
```

脚本构建生产闭包、编译 Job Object启动器，并生成：

```text
resources/dsh/sdk/
├── dsh-runtime-win-x64-<version>.zip
└── dsh-runtime-win-x64-<version>.manifest.json
```

升级源码版本时必须同时完成以下步骤：

1. 将 `resources/dsh/upstream.json` 的 `repository`与 `commit`更新为经过审核的确切上游版本，不使用浮动分支。
2. 以新提交为基线重新生成并审核 `resources/dsh/patches/mw-runtime.patch`，解决无法应用或行为变化的部分。
3. 必要时更新 `runtime_version`与 `node_major`，完成 DSH协议、只读 Web和 Windows Runtime测试。
4. 运行一键脚本，提交新的锁文件、补丁、ZIP和 manifest；四者必须一起更新。

不要手工修改 manifest中的大小、归档哈希或补丁哈希；脚本会根据真实文件生成并复核。

`AgentService.spec` 会再次校验锁定 commit、补丁 SHA-256、完整 ZIP、大小和归档 SHA-256，并把 ZIP与 manifest放入 `AgentService.exe`。SDK缺失、损坏，或者锁文件、补丁与 SDK不一致时，EXE构建立即失败。
注: 任一制品不存在、损坏或版本不符，后端 EXE构建立即失败。应用启动时不解压 SDK；用户第一次安装或第一次运行 DSH子 Agent时才从 EXE内置 ZIP解压到运行目录。

### Electron 桌面安装包（推荐）

当前正式发布形态是 **Electron 桌面端 + 内置后端 exe + NSIS 安装包**：

- Electron 负责桌面窗口、托盘、悬浮窗和安装器。
- `AgentService.exe` 作为内置后端放入安装包的 `resources/backend/`。
- 默认资源模板放入安装包的 `resources/default-resources/`。
- 运行时由 Electron 拉起后端,窗口加载 `http://127.0.0.1:8002`。
- Electron 只接受 `/health` 返回 MetaWeave 固定健康标识的后端；监听端口的其他进程不会被误判为就绪，内置后端在启动期间退出时会立即显示退出原因。
- 安装器允许用户选择安装目录。
- `runtime/` 不进入安装包。数据库、模型缓存、日志和上传文件在用户数据目录首次运行时自动生成；知识库 Markdown 与 frontmatter 则保存在各知识库自己的 `.mw/` 中。

```bash
cd editor
npm ci
npm run dist:win
```

`dist:win` 不会自动执行类型检查、Lint 或测试；正式发布前应先按“测试与质量检查”一节独立完成所需门禁。

构建过程会依次执行：

0. `predist:win`: 调用 Electron 自带的安装脚本检查 `node_modules/electron/dist`；缺失时先从缓存或网络补齐，失败则立即中止。
1. `npm run build-only`: 构建前端静态资源到 `editor/dist/`。
2. `npm run prepare:default-resources`: 生成安装包资源模板到 `editor/.packaging/default-resources/`。
3. `npm run build:backend`: 使用 `pyinstaller --clean` 读取根目录 `AgentService.spec`，校验并内置 DSH SDK，生成 `dist/AgentService.exe`；SDK缺失时此步直接失败。
4. `npm run build:win-installer`: 再次确认 Electron 运行时存在，为本次构建创建独立时间戳目录，并调用 electron-builder 生成 Windows NSIS 安装包。

PyInstaller 开始时会把 `editor/dist/` 复制到唯一临时快照，后续归档只读取该不可变副本，避免另一个 Vite 构建替换哈希资源后生成残缺 exe；进程退出时自动删除快照。

资源模板规则：

```text
editor/.packaging/default-resources/
├── mcp/
│   └── example.json      # MCP 配置模板
├── safety/               # 从 resources/safety 原样复制
├── skills/               # 从 resources/skills 原样复制
└── knowledge/            # 只创建空目录,不复制本地知识库内容
```

最终产物：

```text
editor/release/
└── build-YYYYMMDD-HHMMSS/
    ├── MetaWeave Setup <version>.exe   # 安装包,安装时可选择路径
    ├── MetaWeave Setup <version>.exe.blockmap
    └── win-unpacked/                   # 免安装展开目录,用于调试
```

每次运行都会保留一个新的时间戳目录，确认最终安装包后应删除旧目录，避免数 GiB 的重复产物长期累积。

### 后端 exe（单独构建）

如果只需要后端单文件 exe,可在根目录单独执行：

```bash
# 安装后端依赖
python -m pip install -r agent_service/requirements.txt

# exe 内含前端，必须先生成 editor/dist
npm --prefix editor run build-only

# 打包（读取 AgentService.spec）
pyinstaller --clean AgentService.spec
```

也可以在前端目录执行 `npm run build:backend`，但仍需事先生成 `editor/dist/`。

产物为 `dist/AgentService.exe`。当前 `.spec` 收集：

- 后端程序、Python 依赖与原生动态库；
- `editor/dist/` 的稳定快照；
- `agent_service/core/db/alembic/` 与根目录 `alembic.ini`。
- 固定版本的 `resources/dsh/sdk/` manifest与 ZIP；缺失、损坏或版本漂移会中止构建。

**除 `resources/dsh/sdk/` 外，不要把整个 `resources/` 或 `runtime/` 放入 PyInstaller datas**。默认资源由 Electron安装包外置携带，运行数据必须保留在可写用户目录。当前 DSH SDK ZIP固定增加约 66.0 MB；Torch、Transformers、PaddleOCR、OpenCV、SciPy等科学计算运行库也随 EXE分发，本地模型权重仍不进入 EXE。

### 部署结构

安装后的结构大致如下：

```text
MetaWeave/
├── MetaWeave.exe
├── resources/
│   ├── backend/
│   │   └── AgentService.exe
│   └── default-resources/
│       ├── mcp/
│       ├── safety/
│       ├── skills/
│       └── knowledge/
└── ...
```

首次运行后,Electron 会把默认资源模板复制到用户数据目录,并通过环境变量让后端使用该目录：

```text
%APPDATA%/MetaWeave/
├── .env
├── resources/           # 首次运行从安装包模板复制，之后不覆盖用户修改
│   ├── knowledge/       # 创建空目录，启动不自动灌库，按需触发
│   ├── mcp/             # 首次复制 example.json 模板,可放 .json MCP 服务器配置
│   ├── safety/          # 首次复制 sensitive_words.json，可在设置中持久化修改
│   └── skills/          # 首次复制内置 Skill
└── runtime/             # 自动生成: db/ models/ logs/ uploads/ assets/ trash/
```

> **读取规则**：正式安装包运行时以后端收到的 `AGENT_PROJECT_ROOT=app.getPath('userData')` 为准；Windows 默认通常是 `%APPDATA%/MetaWeave`。`resources/` 是用户可编辑目录，`runtime/` 是运行期数据目录，二者都不写入安装目录和后端 exe。

### 运行方式

桌面安装包安装完成后,直接启动 `MetaWeave`。Electron 会自动拉起内置后端并打开桌面窗口。

如需调试后端 exe,也可以单独运行：

```bash
AgentService.exe
```

后端单独运行时提供 API 和前端页面：`http://127.0.0.1:8002`。`runtime/`、外置 `resources/` 目录骨架和 `.env` 模板会在首次启动时自动生成。Agent 可以使用 `.env` 或客户端设置中的远程模型，也可以使用用户确认下载的本地 Qwen。单独运行后端 exe 时如果希望模拟安装包行为，可手动设置 `AGENT_PROJECT_ROOT` 和 `AGENT_BASE_DATA_DIR`。

单独运行 exe 只会创建 `resources/` 目录骨架，不会像 Electron 安装包一样复制默认 MCP、安全规则和 Skill。需要完整默认资源时，应把安装包的 `default-resources` 内容复制到项目根目录的 `resources/`，或直接从 `win-unpacked/MetaWeave.exe` 启动桌面应用。未配置远程模型时，也可以在客户端确认下载本地 Qwen 后使用 Agent。

## 构建产物与清理

以下目录均可重新生成，不属于源码：

```text
build/                 # PyInstaller 中间文件
dist/                  # 后端 exe
editor/dist/           # Vite 前端产物
editor/.packaging/     # 安装包默认资源 staging
editor/release/        # NSIS 与 win-unpacked 输出
```

发布后可以只保留确认过的 `dist/AgentService.exe` 或最终 `MetaWeave Setup <version>.exe`，删除其余构建目录。不要把根目录 `runtime/` 当作构建垃圾：其中包含数据库、用户设置、会话、上传文件和其他需要保留的应用数据。
