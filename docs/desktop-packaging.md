# 桌面版（Windows / macOS arm64）使用与打包说明

桌面版把 Web 工作台装进一个原生窗口（Windows 使用 pywebview + WebView2，macOS 使用 pywebview + WKWebView），双击即用，**无需安装 Python**。功能与 `python app.py` 启动的 Web 版完全一致，另附命令行版（Windows 为 `CampusRunningGenCLI.exe`，macOS 为 `CampusRunningGenCLI`）。

## 获取方式

| 方式 | 下载 | 适合谁 |
| ------ | ------ | -------- |
| Windows 安装版 | Release 页的 `CampusRunningGen-Setup-v<版本>-win64.exe` | 普通用户，图形化安装向导 |
| Windows 便携版 | Release 页的 `CampusRunningGen-v<版本>-win64.zip` | 免安装、可放 U 盘、删除文件夹即卸载 |
| macOS 安装版 | Release 页的 `CampusRunningGen-Setup-v<版本>-macos-arm64.pkg` | Apple Silicon Mac，标准安装体验（推荐） |
| macOS 便携版 | Release 页的 `CampusRunningGen-v<版本>-macos-arm64.zip` | Apple Silicon Mac，免安装、可放 U 盘 |
| 源码运行 | 克隆仓库后 `python desktop.py` | 开发者，见[构建指南](#构建指南开发者) |

下载入口：[GitHub Releases](https://github.com/EmberCollective/CampusRunning/releases)

## 系统要求

### Windows

- Windows 10 / 11（64 位）
- **WebView2 运行时**：Windows 11 与保持更新的 Windows 10 通常已内置，无需额外操作。若缺失，程序会自动降级——用系统默认浏览器打开 Web 界面，功能不受影响，**不阻断使用**。也可手动安装 [WebView2 Evergreen Bootstrapper](https://developer.microsoft.com/microsoft-edge/webview2/) 获得完整桌面窗口体验。

### macOS

- Apple Silicon（arm64）Mac
- **安装版（推荐）**：双击 pkg 安装到 `/Applications`。首次打开安装包若被拦截，按[Gatekeeper 放行](#macos-gatekeeper-放行)操作一次；安装出的应用不带隔离标记，之后双击即用
- **便携版**：解压 zip 得到 `CampusRunningGen.app`，放行后双击运行；命令行版位于 `CampusRunningGen.app/Contents/MacOS/CampusRunningGenCLI`
- 未配置 Apple 开发者证书签名与公证，首次使用的放行操作均源于此（详见下文）

### 联网说明

地图瓦片（高德 / Leaflet）与 Google Fonts 需要联网加载。**完全离线时**地图区域会空白，但轨迹生成、文件导出等核心功能全部正常——只在导地图预览时才需要网络。

## 高德地图配置

桌面版中使用「官方」地图档或地址搜索功能时，推荐通过配置文件设置高德 Key，以避免 WebView2 的 localStorage 持久化问题：

1. 在程序目录下的 `config` 文件夹中找到 `amap_key.json` 文件。
2. 用文本编辑器打开，填入你的 Key 和安全密钥：

   ```json
   {
     "key": "你的高德JS API Key",
     "securityJsCode": "你的安全密钥"
   }
   ```

3. 保存文件后重启桌面应用，高德地图「官方」档和地址搜索功能即可使用。

> **配置优先级**：配置文件 > 浏览器 localStorage。如果配置文件中已填写有效的 Key，页面内设置的 Key 将被忽略。

## 首次运行

### SmartScreen / 杀软提示

Windows 安装包与可执行文件目前**没有代码签名**，首次运行时 SmartScreen 可能弹出「已保护你的电脑」提示：

1. 点击「更多信息」
2. 点击「仍要运行」

部分杀毒软件也可能对未签名程序告警，放行即可。

### macOS Gatekeeper 放行

安装包与 app 均未签名未公证，新版 macOS 首次使用会被 Gatekeeper 拦截，需人工放行一次：

- **安装版（pkg）**：双击被拦截时，打开「系统设置 → 隐私与安全性」，点击「仍要打开」；或在终端对 pkg 执行 `xattr -d com.apple.quarantine CampusRunningGen-Setup-*.pkg` 后再双击。安装完成后 `/Applications` 中的应用**不再需要任何放行操作**
- **便携版（zip）**：解压后在终端执行 `xattr -dr com.apple.quarantine CampusRunningGen.app`，再双击 app
- macOS 15 起已移除「右键 → 打开」绕过方式；若弹窗为「已损坏，应移到废纸篓」（签名校验失败类），系统设置里**不会**出现「仍要打开」按钮，只能用上述 `xattr` 命令
- 「仍要打开」按钮只会在刚被拦截后短暂出现在「隐私与安全性」页面最底部，重新下载或隔一段时间后失效，找不到时直接用 `xattr` 命令最稳妥

### 校验 sha256

每个 Release 页面会公示全部附件的 sha256 值。下载后建议核对：

```powershell
Get-FileHash .\CampusRunningGen-Setup-v1.0.0-win64.exe -Algorithm SHA256
```

比对结果与 Release 页公示值一致即可放心使用。macOS 可使用：

```bash
shasum -a 256 CampusRunningGen-v1.0.0-macos-arm64.zip
```

## 数据位置

| 版本 | config/ 与 output/ 所在 |
| ------ | -------------------------- |
| Windows 安装版 | `%LOCALAPPDATA%\CampusRunningDataGeneration` |
| Windows 便携版 | exe 同级目录（运行后自动出现） |
| macOS 便携版 | 可执行文件同级目录（运行后自动出现） |
| macOS 安装版 | `~/CampusRunningDataGeneration`（`/Applications` 下程序目录不可写时自动回退） |

- **便携版即拷即用**：Windows 整个文件夹可放 U 盘携带；macOS 可移动整个 `CampusRunningGenerator` 文件夹。配置与生成结果随文件夹走；删除文件夹即完全卸载，Windows 无注册表残留。
- **回退机制**：若 exe 所在目录不可写（如放在 `C:\Program Files` 下直接运行），便携版也会自动改用 `%LOCALAPPDATA%\CampusRunningDataGeneration` 存放数据。

## 恢复出厂默认

- 删除**单个**内置轨迹或模板文件后重启，该文件会自动恢复；你对已有文件的修改始终保留。
- 想**完全恢复出厂设置**：关闭程序后删除数据目录下整个 `config/` 文件夹再启动，内置配置将全部重建。注意：文件夹内你自建的轨迹与模板也会一并删除，请先备份需要的文件。

## 生成过程中关闭窗口会怎样

文件写入是**逐文件、原子操作**：已经生成完成的文件完整有效，可以正常导入运动软件；尚未完成的任务被中断，不会留下半损坏的文件。中断的任务重新生成一次即可。

## 构建指南（开发者）

### 前置条件

| 工具 | 版本 | 说明 |
| ------ | ------ | ------ |
| Python | 3.13+ | 建议使用 venv 隔离环境 |
| PyInstaller | — | 随 `requirements-desktop.txt` 安装 |
| Inno Setup 6 | 6.x | 仅打安装包需要；[官网下载](https://jrsoftware.org/isinfo.php)或 `choco install innosetup` |

### 1. 安装依赖

```bash
python -m venv .venv
source .venv/Scripts/activate    # Windows Git Bash；CMD 用 .venv\Scripts\activate.bat
# macOS / Linux 使用：source .venv/bin/activate
pip install -r requirements.txt -r requirements-desktop.txt
```

### 2. PyInstaller 打包

```bash
pyinstaller campus_running.spec --noconfirm --clean
```

产物在 `dist/CampusRunningGenerator/`：

```text
dist/CampusRunningGenerator/
├── CampusRunningGen.exe        # Windows 桌面窗口版（无控制台；macOS 为 CampusRunningGen）
├── CampusRunningGenCLI.exe     # Windows 命令行版（控制台；macOS 为 CampusRunningGenCLI）
└── _internal/                  # 运行时依赖，与 exe 同发同删
```

首次运行后，exe 旁会自动出现 `config/`（轨迹与模板配置）、`output/`（生成结果）与 `desktop.log`（桌面端日志）。

### 3. Inno Setup 安装包

```bash
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss
```

产物：`dist/CampusRunningGen-Setup-v<版本>-win64.exe`

### 4. zip 便携包

Windows（PowerShell）：

```powershell
Compress-Archive -Path dist/CampusRunningGenerator -DestinationPath dist/CampusRunningGen-v<版本>-win64.zip
```

macOS（保留可执行权限与签名，解压后仍是完整 .app）：

```bash
ditto -c -k --keepParent dist/CampusRunningGen.app dist/CampusRunningGen-v<版本>-macos-arm64.zip
```

### 5. macOS PKG 安装包

```bash
mkdir -p pkg-root
cp -R dist/CampusRunningGen.app pkg-root/
pkgbuild \
  --root pkg-root \
  --identifier io.github.yushenliu06.campusrunninggen \
  --version <版本，不带前导 v> \
  --install-location /Applications \
  dist/CampusRunningGen-Setup-v<版本>-macos-arm64.pkg
```

注意：打包前确认 `.app` 签名完好（`codesign --verify --deep --strict`），且**不要**直接运行 `.app` 内的 CLI 做测试——其首跑会把默认配置播种到 `Contents/MacOS/config/`，破坏签名资源封印（冒烟测试请用裸 COLLECT 目录 `dist/CampusRunningGenerator/CampusRunningGenCLI`）。

### 源码方式运行桌面窗口

不打包也可直接体验桌面窗口：

```bash
python desktop.py
```

### CI 自动发布

向仓库推送 `v*` 格式的 tag（如 `v1.0.0`）即触发 `.github/workflows/release.yml`：自动完成 Windows 安装包、Windows 便携 zip、macOS arm64 PKG 安装包与 macOS arm64 便携 zip 构建，并附 sha256 校验值发布到 [GitHub Releases](https://github.com/EmberCollective/CampusRunning/releases)。日常开发无需手动执行上述构建步骤。
