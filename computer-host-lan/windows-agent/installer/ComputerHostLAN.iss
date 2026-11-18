; Computer Host LAN — experimental Windows graphical installer.
; Reuses the existing ZIP installer scripts; never modifies ProgramData state.
; Build only in CI until Windows 11 upgrade/migration hardware feedback passes.
#define IntegrationVersion "0.5.3-beta.1"
[Setup]
AppId={{B7B83C5C-78B1-4F5F-9BDF-4D5B9D07C12B}
AppName=Computer Host LAN - Windows Agent
AppVersion={#IntegrationVersion}
AppPublisher=Computer Host LAN (SmartThings Community)
AppPublisherURL=https://github.com/ldeora/SmartThingsEdgeDrivers
AppSupportURL=https://github.com/ldeora/SmartThingsEdgeDrivers/issues
DefaultDirName={autopf}\Computer Host Agent
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
Compression=lzma2
SolidCompression=yes
OutputDir=output
OutputBaseFilename=computer-host-lan-v{#IntegrationVersion}-windows-x64-unsigned-setup
UninstallDisplayName=Computer Host LAN - Windows Agent
CloseApplications=no
RestartApplications=no
ChangesEnvironment=no

[Files]
; Inno owns Program Files; the PowerShell script reuses already-installed files.
Source: "..\publish\win-x64\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\scripts\Install-WindowsAgent.ps1"; DestDir: "{app}\Installer"; Flags: ignoreversion
Source: "..\scripts\Uninstall-WindowsAgent.ps1"; DestDir: "{app}\Installer"; Flags: ignoreversion
Source: "..\scripts\Prepare-WindowsAgentUpgrade.ps1"; Flags: dontcopy
Source: "..\publish\hub-discovery\ComputerHost.HubDiscovery.exe"; Flags: dontcopy

[UninstallRun]
; Remove only our service and firewall; Inno removes tracked files. State
; intentionally survives uninstall in ProgramData for a later reinstallation.
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File ""{app}\Installer\Uninstall-WindowsAgent.ps1"" -KeepProgramFiles"; Flags: runhidden waituntilterminated

[Run]
Filename: "https://bestow-regional.api.smartthings.com/invite/1J2Qy7ZkxL20"; Description: "Open the SmartThings driver invitation"; Flags: shellexec postinstall skipifsilent unchecked

[Code]
var
  HubPage: TWizardPage;
  HubSelect: TNewComboBox;
  StatusText: TNewStaticText;
  LocalSubnetCheck: TNewCheckBox;
  PowerCheck: TNewCheckBox;
  Searched: Boolean;

function IsValidIPv4(const Address: String): Boolean;
var
  I, StartPos, Count, N, FirstOctet: Integer;
  Part: String;
begin
  Result := False;
  if (Length(Address) < 7) or (Length(Address) > 15) then Exit;
  Count := 0;
  StartPos := 1;
  FirstOctet := -1;
  for I := 1 to Length(Address) + 1 do
  begin
    if (I > Length(Address)) or (Address[I] = '.') then
    begin
      Part := Copy(Address, StartPos, I - StartPos);
      if (Length(Part) < 1) or (Length(Part) > 3) then Exit;
      N := StrToIntDef(Part, -1);
      if (N < 0) or (N > 255) then Exit;
      Count := Count + 1;
      if Count = 1 then FirstOctet := N;
      StartPos := I + 1;
    end
    else if (Address[I] < '0') or (Address[I] > '9') then Exit;
  end;
  Result := (Count = 4) and (FirstOctet > 0) and
    (FirstOctet <> 127) and (FirstOctet < 224) and
    (Address <> '255.255.255.255');
end;

function WasPowerEnabled: Boolean;
var
  RawConfig: AnsiString;
  Config: String;
begin
  Result := False;
  if LoadStringFromFile(ExpandConstant('{autopf}\Computer Host Agent\appsettings.json'), RawConfig) then
  begin
    Config := LowerCase(String(RawConfig));
    StringChangeEx(Config, ' ', '', True);
    StringChangeEx(Config, #13, '', True);
    StringChangeEx(Config, #10, '', True);
    StringChangeEx(Config, #9, '', True);
    Result := Pos('"enablepowercontrol":true', Config) > 0;
  end;
end;

procedure SearchForHubs(Sender: TObject);
var
  ExitCode, I, Sep, Count: Integer;
  FileName, Address: String;
  Lines: TArrayOfString;
begin
  Searched := True;
  StatusText.Caption := 'Searching for SmartThings hubs on the local network...';
  HubSelect.Items.Clear;
  HubSelect.Text := '';
  try
    ExtractTemporaryFile('ComputerHost.HubDiscovery.exe');
    FileName := ExpandConstant('{tmp}\smartthings-hubs.txt');
    DeleteFile(FileName);
    if not Exec(ExpandConstant('{tmp}\ComputerHost.HubDiscovery.exe'),
      '--output "' + FileName + '"', '', SW_HIDE, ewWaitUntilTerminated, ExitCode) or
      (ExitCode <> 0) or (not LoadStringsFromFile(FileName, Lines)) then
    begin
      StatusText.Caption := 'Discovery unavailable. Enter the hub IP or use LocalSubnet.';
      Exit;
    end;
    Count := 0;
    for I := 0 to GetArrayLength(Lines) - 1 do
    begin
      Sep := Pos('|', Lines[I]);
      if Sep <= 1 then Continue;
      Address := Copy(Lines[I], 1, Sep - 1);
      if IsValidIPv4(Address) then
      begin
        HubSelect.Items.Add(Address + ' (' +
          Copy(Lines[I], Sep + 1, Length(Lines[I]) - Sep) + ')');
        Count := Count + 1;
      end;
    end;
    if Count = 1 then
    begin
      HubSelect.ItemIndex := 0;
      LocalSubnetCheck.Checked := False;
      StatusText.Caption := 'SmartThings hub found. Confirm the address or enter another.';
    end
    else if Count > 1 then
    begin
      StatusText.Caption := 'Multiple hubs found. Select the correct IP from the list.';
      LocalSubnetCheck.Checked := False;
    end
    else
      StatusText.Caption := 'No hub detected. Enter its IP or allow LocalSubnet on Private networks.';
  except
    StatusText.Caption := 'Discovery unavailable. Enter the hub IP or use LocalSubnet.';
  end;
end;

procedure InitializeWizard;
var
  Button: TNewButton;
  LabelText: TNewStaticText;
  SilentHub: String;
begin
  HubPage := CreateCustomPage(wpWelcome, 'SmartThings hub', 'Automatic local discovery and secure firewall scope');
  LabelText := TNewStaticText.Create(HubPage);
  LabelText.Parent := HubPage.Surface;
  LabelText.Caption := 'Hub IPv4 address (automatically detected when available):';
  LabelText.Top := ScaleY(4);
  HubSelect := TNewComboBox.Create(HubPage);
  HubSelect.Parent := HubPage.Surface;
  HubSelect.Left := 0;
  HubSelect.Top := LabelText.Top + LabelText.Height + ScaleY(6);
  HubSelect.Width := ScaleX(300);
  HubSelect.Style := csDropDown;
  Button := TNewButton.Create(HubPage);
  Button.Parent := HubPage.Surface;
  Button.Caption := 'Search again';
  Button.Left := HubSelect.Width + ScaleX(8);
  Button.Top := HubSelect.Top - ScaleY(1);
  Button.Width := HubPage.SurfaceWidth - Button.Left;
  Button.OnClick := @SearchForHubs;
  StatusText := TNewStaticText.Create(HubPage);
  StatusText.Parent := HubPage.Surface;
  StatusText.Top := HubSelect.Top + HubSelect.Height + ScaleY(12);
  StatusText.Width := HubPage.SurfaceWidth;
  StatusText.AutoSize := False;
  StatusText.Height := ScaleY(44);
  StatusText.Caption := 'The installer will search the local network when this page opens.';
  LocalSubnetCheck := TNewCheckBox.Create(HubPage);
  LocalSubnetCheck.Parent := HubPage.Surface;
  LocalSubnetCheck.Top := StatusText.Top + StatusText.Height + ScaleY(5);
  LocalSubnetCheck.Width := HubPage.SurfaceWidth;
  LocalSubnetCheck.Caption := 'Allow any computer on the local subnet (Private networks only)';
  LocalSubnetCheck.Checked := False;
  PowerCheck := TNewCheckBox.Create(HubPage);
  PowerCheck.Parent := HubPage.Surface;
  PowerCheck.Top := LocalSubnetCheck.Top + LocalSubnetCheck.Height + ScaleY(16);
  PowerCheck.Width := HubPage.SurfaceWidth;
  PowerCheck.Caption := 'Enable authenticated shutdown, reboot and suspend';
  PowerCheck.Checked := WasPowerEnabled();
  if PowerCheck.Checked then
    StatusText.Caption := 'Existing power control detected; the setting will be preserved.';

  SilentHub := ExpandConstant('{param:HUBIP|}');
  if SilentHub <> '' then HubSelect.Text := SilentHub;
  if ExpandConstant('{param:LOCALSUBNET|0}') = '1' then
    LocalSubnetCheck.Checked := True;
  if ExpandConstant('{param:ENABLEPOWER|}') <> '' then
    PowerCheck.Checked := ExpandConstant('{param:ENABLEPOWER|0}') = '1';
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if (CurPageID = HubPage.ID) and (not Searched) and
    (not WizardSilent) and (HubSelect.Text = '') then
    SearchForHubs(nil);
end;

function SelectedHubIP: String;
var
  Selected: String;
  CutAt: Integer;
begin
  Selected := Trim(HubSelect.Text);
  CutAt := Pos(' (', Selected);
  if CutAt > 0 then Selected := Copy(Selected, 1, CutAt - 1);
  Result := Selected;
end;

function ValidConfiguration: Boolean;
begin
  Result := LocalSubnetCheck.Checked or IsValidIPv4(SelectedHubIP());
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (CurPageID = HubPage.ID) and not ValidConfiguration() then
  begin
    MsgBox('Please select or enter your SmartThings hub IPv4, or enable the LocalSubnet fallback.',
      mbError, MB_OK);
    Result := False;
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ExitCode: Integer;
  Params: String;
begin
  Result := '';
  if not ValidConfiguration() then
  begin
    Result := 'Missing hub address. Use /HUBIP=192.168.1.20 or /LOCALSUBNET=1 in silent mode.';
    Exit;
  end;
  ExtractTemporaryFile('Prepare-WindowsAgentUpgrade.ps1');
  Params := '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' +
    ExpandConstant('{tmp}\Prepare-WindowsAgentUpgrade.ps1') + '"';
  if not Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
    Params, '', SW_HIDE, ewWaitUntilTerminated, ExitCode) or (ExitCode <> 0) then
    Result := 'Unable to stop or validate the existing Computer Host Agent service. ' +
      'No application files were replaced. Review the installation log.';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Params: String;
  ExitCode: Integer;
begin
  if CurStep <> ssPostInstall then Exit;
  Params := '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' +
    ExpandConstant('{app}\Installer\Install-WindowsAgent.ps1') +
    '" -PublishedDirectory "' + ExpandConstant('{app}') + '" -UseExistingFiles';
  if not LocalSubnetCheck.Checked then
    Params := Params + ' -HubIPv4 ' + SelectedHubIP();
  if PowerCheck.Checked then Params := Params + ' -EnablePower';
  if not Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
    Params, '', SW_HIDE, ewWaitUntilTerminated, ExitCode) or (ExitCode <> 0) then
    RaiseException('Computer Host Agent service installation failed. ' +
      'The setup log contains details; run the supplied installation script for diagnosis.');
end;
