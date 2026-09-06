; ---------------------------------------------------------------------------
; 校园跑步数据生成器 - Inno Setup 安装脚本（Inno Setup 6，per-user 免管理员）
;
; 本地构建前置：
;   1. 先完成 PyInstaller 打包（见 campus_running.spec），确保
;      dist\CampusRunningGenerator\ 目录已生成
;   2. 安装 Inno Setup 6：https://jrsoftware.org/isdl.php
;
; 编译命令（ISCC.exe 需加入 PATH，或用安装目录下的完整路径）：
;   ISCC.exe installer.iss
;
; 产物：dist\CampusRunningGen-Setup-{版本}-win64.exe
;
; 注意：本文件必须保存为 UTF-8 with BOM，否则中文会按 ANSI 解析而乱码
; ---------------------------------------------------------------------------

#define MyAppName "校园跑步数据生成器"
; 版本号：默认 3.1.0（跟随发布 tag，次版本号递增）；CI 可用
; ISCC /DMyAppVersion=v<tag> 注入覆盖
#ifndef MyAppVersion
#define MyAppVersion "3.1.0"
#endif
#define MyAppPublisher "EmberCollective"
#define MyAppExeName "CampusRunningGen.exe"

[Setup]
; AppId 固定 GUID 且永不更改：升级安装时覆盖同一注册表项，
; 而不是在"添加或删除程序"里并列出多个卸载项
AppId={{8C1A7B2D-3F47-4E8A-9C5D-6B21E0F4A7D8}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
; per-user 安装到用户目录：双击即装，不弹 UAC、不需要管理员权限
DefaultDirName={localappdata}\Programs\CampusRunningGenerator
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=dist
OutputBaseFilename=CampusRunningGen-Setup-{#MyAppVersion}-win64
; 安装器与卸载项图标（assets\icon.ico 由 scripts/make_icon.py 生成）
SetupIconFile=assets\icon.ico
; 运行时解析到已安装的 exe，卸载列表图标即刻生效
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
; 简中语言包随仓库分发（installer/ChineseSimplified.isl，UTF-8 BOM）——
; winget/choco 渠道的 Inno Setup 不附带非官方语言包，统一引用本地副本
Name: "chinesesimplified"; MessagesFile: "installer\ChineseSimplified.isl"

[Tasks]
; 桌面快捷方式：默认勾选（Inno 中 Task 不写 Flags: unchecked 即默认选中）
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "dist\CampusRunningGenerator\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; 安装完成页可选勾选"运行"，直接启动 GUI；静默安装（/SILENT）时跳过
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
