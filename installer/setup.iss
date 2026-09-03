; 无损鉴别-章鱼出品V1 安装包脚本 (Inno Setup 6)
; 编译: ISCC.exe installer\setup.iss

#define AppName "无损鉴别-章鱼出品V1"
#define AppVersion "1.0.0"
#define AppPublisher "无敌章鱼哥"
#define AppExe "OctopusLosslessV1.exe"

[Setup]
AppId={{8F3E2A1C-7B4D-4E5F-9A6B-C1D2E3F40506}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\Programs\OctopusLosslessV1
DefaultGroupName={#AppName}
OutputDir=output
OutputBaseFilename=无损鉴别-章鱼出品V1_Setup_v1.0.0
SetupIconFile=..\app\resources\app.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0

[Languages]
Name: "chinesesimplified"; MessagesFile: "ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务:"

[Files]
Source: "..\dist\OctopusLosslessV1\*"; DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\卸载 {#AppName}"; Filename: "{uninstallexe}"
Name: "{userdesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; \
    Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "立即启动 {#AppName}"; \
    Flags: nowait postinstall skipifsilent

[Code]
procedure InitializeWizard;
var
  Footer: TLabel;
begin
  Footer := TLabel.Create(WizardForm);
  Footer.Caption := '本应用由无敌章鱼哥开发 - 章鱼出品，必属精品';
  Footer.Font.Style := [fsBold];
  Footer.Parent := WizardForm;
  Footer.Left := 8;
  Footer.Top := WizardForm.ClientHeight - 28;
  Footer.Anchors := [akLeft, akBottom];
end;
