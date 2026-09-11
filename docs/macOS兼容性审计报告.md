# MetaWeave macOS 兼容性全仓库审计报告

审计日期：2026-09-11  
审计对象：当前工作区受版本控制内容（1,869 个文件）  
结论适用范围：Apple Silicon Mac 与 Intel Mac；开发态、源码运行、桌面打包态和正式分发态分别判断

## 1. 结论摘要

当前项目不是“已有少量 macOS 瑕疵”，而是**正式发行链和若干核心运行链仍以 Windows 为唯一目标**。README 对此表述是诚实的：当前正式版仅支持 Windows 10/11 x86-64；`TODO.md` 也仍保留“macOS完全适配改造”。

本次共确认 22 项 macOS 兼容问题：

| 严重性 | 数量 | 结论 |
| --- | ---: | --- |
| P0 | 0 | 未发现确定会导致灾难性数据破坏或严重安全后果的 macOS 专属问题 |
| P1 | 7 | 覆盖依赖安装、桌面发行、打包态启动、签名公证、Coding Agent 和文件导入核心链路 |
| P2 | 9 | 覆盖 Finder 集成、字体、LaTeX、外部工具发现、终端路径、大小写文件系统、测试与开发入口 |
| P3 | 6 | 覆盖快捷键提示、macOS 原生交互、托盘、系统元数据、Apple Silicon 加速和附带文档 |

如果目标是“可正式发布的 macOS 完全适配”，必须先解决全部 P1；P2 中的 Finder、PATH、LaTeX、测试门禁也应视为发布前必修，而不是发布后优化。

## 2. 严重性定义

- **P0**：确定的数据破坏、严重安全后果，或全部 macOS 用户必然遭遇且无规避的灾难性故障。
- **P1**：安装、启动、正式分发或核心功能阻断；常规用户没有合理规避。
- **P2**：重要但非全局的功能失效、明显错误，或只有手工配置才能规避。
- **P3**：边缘场景、原生体验、文档、维护性或性能问题，影响范围有限。

## 3. P0

### 未确认 P0 问题

外部文件目标路径错误会把文件写到知识库外的异常同级目录，具有数据完整性风险；但当前 macOS Finder 剪贴板又无法可靠传递 `cut` 状态，现有证据更符合“复制失败/错放”而不是“必然删除唯一源文件”，因此列为 P1，不上调为 P0。

## 4. P1 — 阻断级问题

### P1-01：Apple Silicon 上按现有 requirements 无法安装 PyTorch

**证据**

- `agent_service/requirements.txt` 固定 `torch==2.11.0+cpu`、`torchvision==0.26.0+cpu`，并指定 CPU wheel 索引。
- PyTorch 官方 CPU 索引中，Linux/Windows 的 2.11.0 CPU wheel 使用 `+cpu`，macOS ARM64 wheel 的版本是 `2.11.0`，没有 `+cpu`。
- torchvision 0.26.0 同样如此：Linux/Windows wheel 带 `+cpu`，macOS ARM64 wheel 不带。

**触发方式**

在 Python 3.12 Apple Silicon 环境执行文档要求的：

```bash
python -m pip install -r agent_service/requirements.txt
```

**影响**

pip 无法找到满足精确版本 `2.11.0+cpu`/`0.26.0+cpu` 的 macOS 分发物，源码启动在安装阶段即被阻断。

**建议与验收**

- 按平台拆分约束：macOS 使用无 `+cpu` 的同版本 ARM64 wheel，Windows/Linux 保留对应 CPU 变体。
- 在干净的 macOS ARM64 + Python 3.12 环境执行完整 requirements 安装、`pip check` 和关键模块 import。

来源：[PyTorch CPU wheel index](https://download.pytorch.org/whl/cpu/torch/)、[torchvision CPU wheel index](https://download.pytorch.org/whl/cpu/torchvision/)。

### P1-02：Intel Mac 没有可满足当前模型栈的二进制依赖组合

**证据**

- 项目基线是 Python 3.12。
- `paddlepaddle==3.3.1` 的 macOS wheel 只有 `macosx_11_0_arm64`，没有 macOS x86_64。
- 当前 PyTorch 2.11.0 macOS wheel 同样仅列 ARM64。
- Electron 自身支持 Darwin x64 与 arm64，但这不能弥补 Python 后端原生依赖缺口。

**影响**

Intel Mac 无法通过普通 wheel 安装 OCR/模型栈；若“macOS 完全适配”包含仍在使用的 Intel Mac，则安装被阻断。Rosetta 也不能把缺失的 x86_64 Python wheel变出来。

**建议与验收**

- 明确产品矩阵：只支持 Apple Silicon，或为 Intel Mac 选择仍提供 x86_64 wheel 的经过验证的依赖组合。
- README、安装器元数据和下载页必须明确最低 macOS 版本与 CPU 架构。

来源：[PaddlePaddle 3.3.1 PyPI files](https://pypi.org/project/paddlepaddle/3.3.1/)、[Electron supported platforms and architectures](https://www.electronjs.org/docs/latest/tutorial/installation)。

### P1-03：没有 macOS 桌面构建与发行链

**证据**

- `editor/package.json` 只有 `dist:win`、`build:win-installer`、`predist:win`，构建目标为 NSIS。
- `editor/scripts/build-win-installer.cjs` 强制传入 `--win nsis`。
- `extraResources` 只复制 `../dist/AgentService.exe` 到 `backend/AgentService.exe`。
- `AgentService.spec` 的名称、图标、说明和强制资源校验均围绕 `AgentService.exe` 与 Windows DSH SDK。
- `docs/DEVELOPMENT.md` 只描述 NSIS、`win-unpacked` 与 `.exe` 产物。

**影响**

仓库没有可复现的 `.app`/DMG/ZIP 构建命令，也没有 macOS 后端资源映射。直接运行现有发布命令只会走 Windows 路径。

**建议与验收**

- 增加独立 `dist:mac`，显式区分 `mac.arm64`（以及决定支持时的 `mac.x64`）。
- 后端产物使用无 `.exe` 的 macOS 可执行文件，并在 `extraResources` 中按平台映射。
- 在干净 macOS 构建机生成 `.app` 和 DMG/ZIP，检查 bundle 内前端、后端、默认资源、迁移文件和本机原生库架构。

### P1-04：即便手工构建出 `.app`，打包态也不会启动后端

**证据**

`editor/electron/main.cjs:333-335`：

```js
async function startPackagedBackend() {
  if (!app.isPackaged || process.platform !== 'win32') {
    return
  }
```

随后 `app.whenReady()` 无条件调用 `loadPackagedBackend()`，等待 `127.0.0.1:8002`。没有外部后端预先运行时，macOS 包必然进入“内置 Agent 服务未能启动”。此外，`ensurePackagedUserResources()` 也只在 Windows 后端启动分支中被调用，macOS 首次启动不会复制默认 MCP、安全规则与 Skill。

**影响**

打包态桌面应用无法正常进入主界面；这是独立于“有没有生成安装包”的运行时阻断。

**建议与验收**

- 按平台解析后端文件名和启动参数，不要以 `win32` 作为整个启动流程的开关。
- 将默认资源初始化从 Windows 进程启动分支解耦。
- 在未预启任何服务的 Mac 上首次打开 `.app`，验证后端被拉起、`/health` 通过、关闭时只回收本应用创建的后端。

### P1-05：没有 macOS 代码签名与公证流程

**证据**

- `editor/package.json` 没有 macOS `identity`、hardened runtime、entitlements、notarize 或 after-sign 配置。
- 仓库没有 macOS 签名/公证脚本或 CI 密钥配置。
- 开发文档没有 Developer ID、notarytool、staple 或 Gatekeeper 验收步骤。

**影响**

即使产出 `.app`，互联网下载后的应用会触发 Gatekeeper 阻止/警告；要求普通用户执行 `xattr` 或右键绕过不属于可接受的正式发行体验。

**建议与验收**

- 使用 Developer ID Application 签名、hardened runtime 与最小 entitlements，随后 notarize 并 staple。
- 验收 `codesign --verify --deep --strict`、`spctl --assess --type execute`，并在一台从未运行过该应用的 Mac 上验证下载、挂载、拖入 Applications、首次启动。

Electron 官方明确说明 macOS 对外分发需要代码签名和 notarization：[Electron Code Signing](https://www.electronjs.org/docs/latest/tutorial/code-signing)。

### P1-06：DSH Coding Agent 是完整的 Windows x64 专用实现

**证据链**

- `resources/dsh/sdk/*.manifest.json` 固定 `platform: windows`、`node/node.exe`、`dsh-job-launcher.exe`。
- `agent_service/services/dsh_runtime/service.py:263-291` 只查找 `dsh-runtime-win-x64-*`，并主动拒绝非 Windows、非 x64 清单。
- `service.py:192-203` 强制存在 Windows Job launcher。
- `service.py:330-350` 使用 `powershell.exe` 执行 Authenticode 校验。
- `native/dsh_job_launcher.c` 直接包含 `windows.h`，使用 Job Object/CreateProcessW。
- `scripts/build_dsh_windows_bundle.py` 要求 `node.exe`、`cl.exe/gcc.exe`，只生成 Windows bundle。
- `agent_service/services/dsh_adapter/executor.py` 只通过上述 launcher 启动 Runtime。
- 设置页始终展示“Windows x64”。

**额外迁移阻断**

当前 ZIP 解压器逐字节写文件但不恢复 Unix executable mode。即使只把 bundle 换成 `node` 和 macOS launcher，解压后的二进制也很可能没有执行位。

**影响**

代码子 Agent、DSH Web 轨迹和相关管理功能在 macOS 全部不可用；不是改一个文件名即可恢复。

**建议与验收**

- 为 Darwin arm64 设计独立 Runtime manifest、进程树回收方案、权限模型、签名校验和打包链。
- 使用 POSIX process group/信号实现等价生命周期，但必须重新审查 Windows ACL 沙箱语义在 macOS 上的替代方案，不能声称等价而不验证。
- ZIP/tar 解包必须安全保留 executable bit，或从受信清单显式 `chmod`。
- 真机执行跨文件编辑、Git、测试失败修复、取消、超时、宿主崩溃后代回收和三权限模式验收。

### P1-07：嵌套目录的外部文件导入/粘贴会写到知识库外的错误位置

**证据**

以下三处重复实现均强制使用 Windows 分隔符：

- `editor/src/stores/workspace.ts:134-140`
- `editor/src/components/editor_workspace/FileTreePanel.vue:199-205`
- `editor/src/components/editor_workspace/FileResourceManager.vue:220-226`

核心返回值：

```ts
return `${root}\\${child.replace(/\//g, '\\')}`
```

该结果被用于 `files:copy-into-directory`、外部拖入/粘贴、系统剪贴板、打开和 Finder 定位。可执行探针得到：

```text
built:    /Users/alice/Knowledge\papers\a.pdf
dirname:  /Users/alice
expected: /Users/alice/Knowledge/papers/a.pdf
```

在 POSIX 中反斜杠是普通文件名字符，因此 Electron 的 `mkdir` 会创建 `/Users/alice/Knowledge\papers`，而不是 `/Users/alice/Knowledge/papers`。

**影响**

向知识库子目录拖入或粘贴文件时，文件被错放到知识库外，刷新后在文件树中消失；这是核心资料管理链路失效并伴随数据位置异常。

**建议与验收**

- 删除渲染层自造 OS 绝对路径的三份重复实现；由 Electron 主进程使用 `path.join`，或让后端从知识库根与规范化相对路径解析。
- 对复制/移动目标执行知识库范围校验。
- macOS 真机分别验证根目录、两级子目录、中文/空格/组合字符目录的拖入、复制、剪切、冲突覆盖/跳过/重命名。

## 5. P2 — 重要功能问题

### P2-01：文件树与文献库的 Finder/默认应用操作使用无效绝对路径

**证据**

- `FileTreePanel.vue:630-709` 与 `FileResourceManager.vue:591-633` 把 P1-07 的反斜杠路径传给 `shell.showItemInFolder`/`shell.openPath`，或复制给用户。
- `editor/src/views/LiteratureReadingView.vue:215-216` 更直接地把整个绝对路径中的 `/` 全部替换为 `\`。

**影响**

“在 Finder 中显示”“使用默认程序打开”“复制绝对路径”在 macOS 上失败或得到不可用文本；文献阅读页同类入口也失败。

**建议与验收**

由 Electron 主进程接收 `{knowledgeRoot, relativePath}` 后用当前平台 `path.join` 生成路径；验证 Finder 定位、Preview/Office 默认打开和路径复制。

### P2-02：Finder 文件剪贴板没有使用 macOS 原生文件格式

**证据**

- `editor/electron/main.cjs:151-173` 尝试类型定义中不存在的 `clipboard.readFiles()`，否则只解析纯文本。
- `main.cjs:935-965` 尝试不存在的 `clipboard.writeFiles()`，否则只写纯文本。
- 剪切状态通过 Windows `Preferred DropEffect` buffer 读写。
- 项目锁定的 Electron 43 类型面有 `readText/writeText/readBuffer/writeBuffer`，没有 `readFiles/writeFiles`。

**影响**

MetaWeave 与 Finder 之间的文件复制/粘贴无法稳定传递真实文件引用；Finder 的 cut/copy 语义也不会被 Windows 私有格式表达。内部文件粘贴还会叠加 P1-07。

**建议与验收**

Electron 官方的跨平台方式是 `text/uri-list`，在 macOS 映射 `NSFilenamesPboardType`。使用 `pathToFileURL` 写入、`fileURLToPath` 读取，并单独设计 macOS move 语义；验证 MetaWeave→Finder、Finder→MetaWeave、多文件、文件夹与非 ASCII 名称。

来源：[Electron ClipboardItem — Files](https://www.electronjs.org/docs/latest/api/clipboard-item)。

### P2-03：系统字体枚举依赖 macOS 默认不存在的 `fc-list`

**证据**

`editor/electron/main.cjs:855-859` 仅区分 Windows/非 Windows；非 Windows 统一执行 `fc-list : family`。macOS 的系统字体数据库不是 fontconfig，标准系统不保证安装该命令。

**影响**

字体列表通常为空；用户只能依赖手工输入或默认字体，设置页的系统字体发现功能失效。

**建议与验收**

macOS 使用 CoreText/系统 API 或经过验证的跨平台字体枚举库，Linux 才使用 `fc-list`。在未安装 Homebrew/fontconfig 的干净 Mac 上验证中文、英文字体与可变字体。

### P2-04：LaTeX 自动安装在 macOS 明确不可用，但前端仍提供 Windows 动作

**证据**

- `agent_service/services/latex/service.py:32-36` 固定 Windows x64 MiKTeX Setup URL。
- `service.py:272-276` 在非 Windows 直接抛出“目前仅支持 Windows”。
- `service.py:495-518` 可以回退到 PATH 中现有 `pdflatex/xelatex/lualatex`，说明编译本身有部分跨平台基础。
- `LatexPreview.vue` 与编译管理 UI 仍展示“安装 MiKTeX”，没有 Darwin 平台分支。

**影响**

未预装 TeX 的 Mac 用户点击产品提供的修复动作只会失败；安装 MacTeX 后又可能受 P2-05 PATH 影响而仍被判定“未安装”。

**建议与验收**

macOS 隐藏 Windows 安装器，提供 MacTeX/BasicTeX 的明确安装与 PATH 探测；若实现托管安装，必须采用 macOS 原生分发、签名与卸载边界。验证系统 TeX 与托管方案的编译、取消、错误定位和 PDF 预览。

### P2-05：打包应用没有恢复 macOS 登录 Shell/PATH，Homebrew 工具会消失

**证据**

- Electron 直接继承 Finder 启动环境并拉起后端，没有读取登录 shell 环境或补充 `/opt/homebrew/bin`、`/usr/local/bin`。
- 后端用 `shutil.which` 查找 TeX，用裸 `git`/`npx`/`node`/`rg` 等执行 MCP、终端和开发工具。
- 字体代码也以裸 `fc-list` 启动。

**触发条件**

用户从 Finder/Dock 打开 `.app`，依赖通过 Homebrew 或 shell profile 安装，而不在 GUI 进程的基础 PATH 中。

**影响**

系统明明装有工具，应用仍报告不存在；LaTeX、Git、MCP、Agent 终端和部分 bundled Skill 可能失败。从 Terminal 启动 `.app` 可能暂时规避，导致问题难以复现和支持。

**建议与验收**

启动时使用受控、可审计的 macOS PATH 发现策略；不要无边界执行用户 shell profile。分别从 Finder、Dock、Terminal 启动并验证 Homebrew ARM64 与 `/usr/local` Intel 路径。

### P2-06：终端内部 `ls/dir` 会吞掉所有 POSIX 绝对路径

**证据**

`agent_service/services/terminal/command_sandbox.py:1241-1255` 把所有以 `/` 开头的参数当作 Windows 风格标志；未知项也直接 `continue`。

因此：

```text
ls /Users/alice/Knowledge
```

会丢弃 `/Users/alice/Knowledge`，最终回退为列出当前目录 `.`。

**影响**

Agent 无法用内部读取命令检查任何 macOS 绝对路径，且返回结果看似成功、实际目录错误，容易误导后续推理。

**建议与验收**

仅在明确 `cmd` 语义下解析 `/A` 等开关，或只接受白名单中的完整 Windows 开关；POSIX shell 下把 `/...` 作为路径。增加 `/`、`/Users/...`、空格路径与 Windows `/A` 的平台参数化测试。

### P2-07：case-sensitive APFS 上 Git 状态与 Wiki 链接会错误合并路径

**证据**

- `editor/src/stores/git.ts:57-60` 对所有 Git path 无条件 `.toLowerCase()`，并作为 Map key。
- `editor/src/components/editor_workspace/wikiLinks.ts:165-168` 对 Wiki 目标和候选路径无条件 locale-lowercase。

**影响**

在 case-sensitive APFS、区分大小写的磁盘映像或外置卷上，`Readme.md` 与 `README.md` 是两个合法文件，但 Git UI 状态会覆盖，Wiki 解析会歧义或打开错误文件。

**建议与验收**

内部身份键保持规范化分隔符但保留大小写；模糊匹配只能在确认文件系统大小写策略后作为次级回退。用同时存在的大小写异名文件做 Git 与 Wiki 端到端测试。

### P2-08：没有任何 macOS CI、打包门禁或桌面冒烟

**证据**

- 仓库不存在 `.github/` CI 配置。
- 搜索测试只找到 Windows 发行断言；`tests/test_packaging_configuration.py` 明确是“Windows 发布配置”。
- `tests/test_dsh_runtime_manager.py` 的平台 skip 是 Windows MAX_PATH 回归。
- 前端 E2E fixture 固定 `D:/...` 和 `Windows x64`。
- 没有 Darwin、Apple Silicon、Intel、DMG、codesign、notarize、Finder 或 MacTeX 测试。

**影响**

即使逐项修复，后续依赖升级、Electron 升级和路径修改仍会静默回归；当前“测试全绿”不能对 macOS 提供任何发行信心。

**建议与验收**

至少建立 macOS ARM64 门禁：requirements 安装、后端定向测试、前端单测、PyInstaller、electron-builder、codesign/notarize 校验和打包态 UI 冒烟。若支持 Intel，再增加 x64/Rosetta 矩阵。

### P2-09：开发启动与发布文档没有 macOS 路径

**证据**

- 根目录一键启动只有 `启动.bat`，依赖 `cmd /k`、`netstat -ano`、`findstr`、`taskkill`、`start`。
- DSH 生产入口只有 `scripts/build_dsh_sdk.bat`。
- `docs/DEVELOPMENT.md` 的正式构建、产物结构、运行方式均为 NSIS/EXE/`%APPDATA%`。
- 没有 `.command`/`.sh`、Homebrew/Python universal2 说明、macOS 权限、DMG、签名或故障排查。

**影响**

开发者可以手工在两个终端启动后端和 Electron，但无法按项目的一键流程、SDK 流程或发布手册完成 macOS 工作；操作差异会造成不可复现环境。

**建议与验收**

增加跨平台 Node/Python 启动器或 macOS shell 入口，并写独立开发、测试、打包、签名、公证、卸载和数据目录文档。脚本必须安全识别并只停止本项目进程。

## 6. P3 — 次要兼容与原生体验问题

### P3-01：快捷键提示仍硬编码为 Ctrl

行为处理多数已接受 `ctrlKey || metaKey`，Electron 的 Select All 也会在 Darwin 选择 Meta；但 `CodeEditor.vue`、`FileContextMenu.vue`、`SmartFormsView.vue` 等大量可见提示仍写 `Ctrl+C/S/Z/...`。macOS 用户实际应看到 `⌘`；Redo 应优先展示 `⇧⌘Z`。

### P3-02：缺少 macOS 标准应用菜单、窗口控制与全屏语义

`editor/electron/main.cjs:708-720` 将菜单替换为只有一个 `Edit` 菜单，没有标准 App/Window/Help、About、Preferences、Services、Hide、Quit 等 role。主窗口 `frame:false`，自绘窗口按钮按 Windows 顺序展示“最小化/最大化/关闭”，并调用 `maximize()` 而非 macOS 原生绿色按钮/全屏流程。

这不阻止应用运行，但明显不符合 macOS 交互惯例，也降低键盘与辅助功能可发现性。

### P3-03：菜单栏图标没有采用 macOS template image

`createTray()` 直接读取并缩放 `app.icns`，没有 `nativeImage.setTemplateImage(true)` 或独立黑白模板资源。彩色/深色图标在深色菜单栏下可能对比不足。

### P3-04：知识库文件树会显示并递归 macOS 元数据

`agent_service/services/knowledge_library/file_tree.py:129-142, 509-523` 只硬编码排除 `.git`，没有默认排除 `.DS_Store`、`.AppleDouble`、`__MACOSX` 等。非支持后缀会被标为 ignored，但仍显示并参与目录遍历；选择卷根等宽目录时还可能遇到受保护系统目录。

建议把 macOS 元数据加入默认 ignore，并对不可读目录做逐节点隔离，不能让一个 PermissionError 破坏整棵树。

### P3-05：Apple Silicon 可用的 MPS 没有被利用

`agent_service/services/local_qwen/service.py:135, 314-327` 把模型和张量固定到 CPU；Embedding/OCR 配置也以 CPU 为唯一默认。功能仍可运行，因此不是阻断，但本地 Qwen、Embedding 与部分视觉流程无法利用 Apple GPU，能耗与延迟会明显高于具备 MPS 适配的实现。

若后续支持 MPS，必须先验证算子覆盖、dtype、内存回退和输出一致性，不能只把字符串从 `cpu` 改成 `mps`。

### P3-06：随程序分发的个别 Skill 文档仍只给 Windows 安装路径

`resources/skills/humanizer-zh/README.md:41` 只写 `%USERPROFILE%\.claude\skills\`。这不影响 MetaWeave 核心启动，但会误导 macOS 用户安装/复用该 Skill。

## 7. 已检查且未发现 macOS 阻断的区域

为避免把“没写 macOS 分支”一概误判为不兼容，以下区域也已核查：

- Python 主体路径操作大量使用 `pathlib.Path`，知识库 API 的相对路径通常先统一为 `/`，基础读写、SQLite、Alembic 与 Chroma 目录布局本身没有发现 Windows-only 阻断。
- 临时文件主要使用 `tempfile`，适配 macOS 临时目录。
- gRPC 只对 Windows IPv6 wildcard 做特例，Darwin 走标准地址，未发现反向阻断。
- LaTeX 实际编译命令使用 argv + `shell=False`，已安装且能被 PATH 找到的 MacTeX/TeX Live 可走系统工具链。
- Electron 已包含 `app.icns`，并在 Darwin 选择该图标。
- 前端多数实际键盘监听同时支持 Ctrl 与 Meta；问题主要是提示和菜单结构。
- `package-lock.json` 包含 Rolldown、Oxlint、Lightning CSS 等 Darwin arm64/x64 可选原生绑定；前端依赖安装本身没有发现只锁 Windows binding 的问题。
- PaddlePaddle 3.3.1 已提供 Python 3.12 的 macOS ARM64 wheel；阻断点是 Intel 缺包和 PyTorch `+cpu` 精确约束，而不是“Paddle 完全没有 Mac 版本”。

## 8. 验证记录与局限

### 已执行

- 对 1,869 个受控文件进行目录/扩展名清点。
- 对源码、配置、脚本、测试与 Markdown 扫描：平台判断、Windows API、`.exe/.bat`、PowerShell/cmd、路径分隔符、环境变量、进程、打包、签名、字体、LaTeX、剪贴板、快捷键和测试矩阵。
- 逐段审阅 Electron 主进程/预加载、package/build scripts、PyInstaller spec、requirements、AgentConfig、DSH manager/adapter/native launcher、终端沙箱、LaTeX service、文件树/workspace/文献路径、Git/Wiki path key 与相关文档。
- POSIX 路径探针复现反斜杠目标错位。
- 现有定向测试：

```text
26 passed, 2 skipped, 1 warning
```

覆盖文件：`test_packaging_configuration.py`、`test_node_engine_compatibility.py`、`test_dsh_runtime_manager.py`、`test_latex_service.py`。两个 skip 分别是 Windows MAX_PATH 条件和本机缺少 XeLaTeX；这些测试没有 macOS 运行证据。

- 核验官方 PyTorch/torchvision CPU wheel 索引、PyPI PaddlePaddle 分发文件和 Electron 签名/剪贴板文档。

### 未完成且不能伪装为完成

当前审计主机是 Windows，没有可用的 macOS 真机或 macOS CI runner，因此无法执行：

- `.app`/DMG 实际构建、签名、公证与 Gatekeeper 首启；
- Apple Silicon/Intel requirements 真实安装；
- Finder 文件复制/剪切/显示、Dock/菜单栏、原生菜单、窗口/全屏交互；
- MacTeX、Homebrew PATH、CoreText 字体与 MPS 实测；
- macOS 打包态完整 UI 冒烟。

因此报告中的源码确定性问题和官方发行物结论可信度高；P2-05 GUI PATH、P3 原生体验等仍应在真机验收中复核。

## 9. 建议修复顺序

1. **先定义支持矩阵**：Apple Silicon only，还是同时支持 Intel；最低 macOS 版本是什么。
2. **打通可安装后端**：平台化 requirements，完成干净 Mac 安装与 import 门禁。
3. **打通打包态启动**：macOS PyInstaller 后端、Electron resource mapping、资源初始化与进程回收。
4. **建立签名发行链**：`.app`/DMG、Developer ID、hardened runtime、notarization、staple、Gatekeeper 验收。
5. **修复文件系统核心链**：统一 OS path join、目标范围校验、Finder clipboard、打开/定位/复制路径。
6. **实现或明确降级 DSH**：没有 Darwin Runtime 前，不应把 Windows SDK 管理动作暴露为可用能力。
7. **补齐系统集成**：PATH、字体、MacTeX、菜单、窗口、快捷键、元数据过滤。
8. **最后建立 macOS CI + 真机 UI 冒烟门禁**，再把 README 的“不支持 macOS”改为具体支持矩阵。

## 10. 用户要求对应验收

| 用户要求 | 本报告对应 |
| --- | --- |
| 全面且细致地调查整个项目 | 1,869 文件清点；按后端、Electron、前端、原生代码、依赖、打包、资源、测试、文档逐层审计 |
| 包括文档和代码功能 | 对 README/DEVELOPMENT/ARCHITECTURE/ADAPTER/TODO 与实际启动、文件、Agent、LaTeX、终端、Git、字体等功能交叉核对 |
| 详细查看 mac 不兼容 | 每项给出代码证据、触发条件、影响、修复与真机验收方式 |
| 用 P 以严重性排列穷举 | 22 项按 P0→P3 排列；P0 明确为 0，未把风险夸大成确定缺陷 |
