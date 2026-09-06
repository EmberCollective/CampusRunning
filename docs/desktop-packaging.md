# 桌面版（Windows）使用与打包说明

桌面版把 Web 工作台装进一个原生窗口（pywebview + 系统 WebView2），双击即用，**无需安装 Python**。功能与 `python app.py` 启动的 Web 版完全一致，另附一个命令行版 `CampusRunningGenCLI.exe`。

## 获取方式

| 方式 | 下载 | 适合谁 |
| ------ | ------ | -------- |
| 安装版 | Release 页的 `CampusRunningGen-Setup-<版本>-win64.exe` | 普通用户，图形化安装向导 |
| 便携版 | Release 页的 `CampusRunningGen-v<版本>-win64.zip` | 免安装、可放 U 盘、删除文件夹即卸载 |
| 源码运行 | 克隆仓库后 `python desktop.py` | 开发者，见[构建指南](#构建指南开发者) |

下载入口：[GitHub Releases](https://github.com/EmberCollective/CampusRunning/releases)

## 系统要求

- Windows 10 / 11（64 位）
- **WebView2 运行时**：Windows 11 与保持更新的 Windows 10 通常已内置，无需额外操作。若缺失，程序会自动降级——用系统默认浏览器打开 Web 界面，功能不受影响，**不阻断使用**。也可手动安装 [WebView2 Evergreen Bootstrapper](https://developer.microsoft.com/microsoft-edge/webview2/) 获得完整桌面窗口体验。

### 联网说明

地图瓦片（高德 / Leaflet）与 Google Fonts 需要联网加载。**完全离线时**地图区域会空白，但轨迹生成、文件导出等核心功能全部正常——只在导地图预览时才需要网络。

## 首次运行

### SmartScreen / 杀软提示

安装包与可执行文件目前**没有代码签名**，首次运行时 Windows SmartScreen 可能弹出「已保护你的电脑」提示：

1. 点击「更多信息」
2. 点击「仍要运行」

部分杀毒软件也可能对未签名程序告警，放行即可。

### 校验 sha256

每个 Release 页面会公示全部附件的 sha256 值。下载后建议核对：

```powershell
Get-FileHash .\CampusRunningGen-Setup-v1.0.0-win64.exe -Algorithm SHA256
```

比对结果与 Release 页公示值一致即可放心使用。

## 数据位置

| 版本 | config/ 与 output/ 所在 |
| ------ | -------------------------- |
| 便携版 | exe 同级目录（运行后自动出现） |
| 安装版 | `%LOCALAPPDATA%\CampusRunningDataGeneration` |

- **便携版即拷即用**：整个文件夹可放 U 盘携带，配置与生成结果随文件夹走；删除文件夹即完全卸载，无注册表残留。
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
pip install -r requirements.txt -r requirements-desktop.txt
```

### 2. PyInstaller 打包

```bash
pyinstaller campus_running.spec --noconfirm --clean
```

产物在 `dist/CampusRunningGenerator/`：

```text
dist/CampusRunningGenerator/
├── CampusRunningGen.exe        # 桌面窗口版（无控制台）
├── CampusRunningGenCLI.exe     # 命令行版（控制台）
└── _internal/                  # 运行时依赖，与 exe 同发同删
```

首次运行后，exe 旁会自动出现 `config/`（轨迹与模板配置）、`output/`（生成结果）与 `desktop.log`（桌面端日志）。

### 3. Inno Setup 安装包

```bash
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss
```

产物：`dist/CampusRunningGen-Setup-<版本>-win64.exe`

### 4. zip 便携包

PowerShell：

```powershell
Compress-Archive -Path dist/CampusRunningGenerator -DestinationPath dist/CampusRunningGen-v<版本>-win64.zip
```

### 源码方式运行桌面窗口

不打包也可直接体验桌面窗口：

```bash
python desktop.py
```

### CI 自动发布

向仓库推送 `v*` 格式的 tag（如 `v1.0.0`）即触发 `.github/workflows/release.yml`：自动完成打包、生成安装包与便携 zip，并附 sha256 校验值发布到 [GitHub Releases](https://github.com/EmberCollective/CampusRunning/releases)。日常开发无需手动执行上述构建步骤。
