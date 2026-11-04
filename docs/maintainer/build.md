# 构建与打包（维护者）

> 手册：构建与打包 · [发版流程](release.md) · [工具速查](tools.md)

本文说明如何在本地从源码构建 Windows / macOS 桌面产物（安装包与便携包），并收录打包链路的常见坑。适合需要在发版前本地验证产物、或排查打包问题的维护者。日常发版由 CI 自动完成全部构建、无需本地操作，发版步骤见[发版流程](release.md)；面向最终用户的安装与使用问题见[桌面版文档](../desktop-packaging.md)。

## 产物总览

| 产物 | 平台 | 文件名 | 说明 |
|------|------|--------|------|
| Windows 安装包 | x86_64 | `CampusRunningGen-Setup-v<版本>-win64.exe` | Inno Setup 打包，per-user 免管理员安装 |
| Windows 便携包 | x86_64 | `CampusRunningGen-v<版本>-win64.zip` | 整目录压缩，免安装 |
| macOS 安装包 | arm64 | `CampusRunningGen-Setup-v<版本>-macos-arm64.pkg` | 安装到 /Applications |
| macOS 便携包 | arm64 | `CampusRunningGen-v<版本>-macos-arm64.zip` | 解压即完整 .app |

PyInstaller 构建产物目录（后续步骤的输入）：

```text
dist/CampusRunningGenerator/
├── CampusRunningGen.exe        # Windows 桌面窗口版（无控制台；macOS 为 CampusRunningGen）
├── CampusRunningGenCLI.exe     # Windows 命令行版（控制台；macOS 为 CampusRunningGenCLI）
└── _internal/                  # 运行时依赖，与 exe 同发同删
```

首次运行后，exe 旁会自动出现 `config/`（轨迹与模板配置）、`output/`（生成结果）与 `desktop.log`（桌面端日志）。

## 前置条件

| 工具 | 版本 | 说明 |
|------|------|------|
| Python | 3.13+ | 建议使用 venv 隔离环境 |
| PyInstaller | — | 随 `requirements-desktop.txt` 安装 |
| Inno Setup 6 | 6.x | 仅打 Windows 安装包需要；[官网下载](https://jrsoftware.org/isinfo.php)或 `choco install innosetup` |

## 构建步骤

### 1. 安装依赖

```bash
python -m venv .venv
source .venv/Scripts/activate    # Windows Git Bash；CMD 用 .venv\Scripts\activate.bat
# macOS / Linux 使用：source .venv/bin/activate
pip install -r requirements.txt -r requirements-desktop.txt
```

### 2. PyInstaller 打包

```bash
pyinstaller campus_running.spec --noconfirm
```

> 本地**不要**加 `--clean`：dist 目录常被瞬时文件锁锁住，`--clean` 清目录时会报 `PermissionError`；覆盖式构建无此问题。CI 环境无残留锁，工作流中保留 `--clean`。

产物即上文「产物总览」中的目录树。macOS 平台此步额外产出 `dist/CampusRunningGen.app`（含 Dock 图标与签名结构）。

### 3. Windows 安装包（Inno Setup）

```bash
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss
```

需要指定版本号时通过 `/D` 注入（CI 即此做法）：

```bash
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" "/DMyAppVersion=v3.1.0" installer.iss
```

> Git Bash 下传 `/D` 参数会被 MSYS 路径转换吃掉，需加前缀 `MSYS_NO_PATHCONV=1`。

产物：`dist/CampusRunningGen-Setup-v<版本>-win64.exe`。

### 4. Windows 便携包（zip）

```powershell
Compress-Archive -Path dist/CampusRunningGenerator -DestinationPath dist/CampusRunningGen-v<版本>-win64.zip
```

### 5. macOS 便携包与 PKG 安装包

便携包（ditto 保留可执行权限与签名，解压后仍是完整 .app）：

```bash
ditto -c -k --keepParent dist/CampusRunningGen.app dist/CampusRunningGen-v<版本>-macos-arm64.zip
```

PKG 安装包：

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

> 打包前确认 `.app` 签名完好（`codesign --verify --deep --strict`），且**不要**直接运行 `.app` 内的 CLI 做测试——其首跑会把默认配置播种到 `Contents/MacOS/config/`，破坏签名资源封印，用户侧表现为 Gatekeeper「已损坏，应移到废纸篓」。冒烟测试请用裸 COLLECT 目录的 `dist/CampusRunningGenerator/CampusRunningGenCLI`。

## 源码方式运行桌面窗口

不打包也可直接体验桌面窗口：

```bash
python desktop.py
```

## 常见坑

| # | 坑 | 说明 |
|---|----|------|
| 1 | 只跑 ISCC 会产出混装包 | ISCC 只是把**既有的** `dist/CampusRunningGenerator/` 打进安装包，不重新构建 exe。跳过 PyInstaller 直接跑 ISCC，会得到「文件名是新版、exe 内容是旧版」的混合安装包。任何交付/发版前必须完整走 PyInstaller → ISCC 重建 |
| 2 | 本地 `--clean` 报 PermissionError | 见步骤 2 的引注：本地用覆盖式构建，勿加 `--clean` |
| 3 | Git Bash 的 `/D` 参数失效 | MSYS 路径转换吃掉 `/DMyAppVersion`，加 `MSYS_NO_PATHCONV=1` 前缀 |
| 4 | installer.iss 编码 | 必须保持 UTF-8 **with BOM**（中文注释按 ANSI 解析会乱码）。简体中文语言包已 vendor 在 `installer/ChineseSimplified.isl`，官方渠道不带此语言包，勿改回 `compiler:` 引用 |
