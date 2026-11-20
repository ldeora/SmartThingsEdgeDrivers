; Computer Host LAN — unsigned Windows beta graphical installer.
; Reuses the existing ZIP installer scripts; never modifies ProgramData state.
; Native Windows CI tested. Real Windows 11 hub discovery remains beta scope.
#define IntegrationVersion "0.5.6-beta.1"
[Setup]
AppId={{B7B83C5C-78B1-4F5F-9BDF-4D5B9D07C12B}
AppName=Computer Host LAN - Windows Agent
AppVersion={#IntegrationVersion}
AppPublisher=Computer Host LAN (SmartThings Community)
AppPublisherURL=https://github.com/ldeora/SmartThingsEdgeDrivers
AppSupportURL=https://github.com/ldeora/SmartThingsEdgeDrivers/issues
DefaultDirName={autopf}\Computer Host Agent
DisableWelcomePage=no
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=admin
; Inno Setup 7 builds a native x64 installer, avoiding WOW64 PowerShell module
; and Program Files redirection during service and firewall management.
SetupArchitecture=x64
ArchitecturesAllowed=x64os
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern dynamic
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
; Preserve existing host-side settings on ZIP-to-Setup and Setup-to-Setup upgrades.
; The PowerShell service installer updates only EnablePowerControl after copy.
Source: "..\publish\win-x64\*"; DestDir: "{app}"; Excludes: "appsettings.json"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\publish\win-x64\appsettings.json"; DestDir: "{app}"; Flags: onlyifdoesntexist
Source: "..\scripts\Install-WindowsAgent.ps1"; DestDir: "{app}\Installer"; Flags: ignoreversion
Source: "..\scripts\Uninstall-WindowsAgent.ps1"; DestDir: "{app}\Installer"; Flags: ignoreversion
Source: "..\scripts\Prepare-WindowsAgentUpgrade.ps1"; Flags: dontcopy
Source: "..\scripts\Restore-WindowsAgentUpgrade.ps1"; Flags: dontcopy
Source: "..\scripts\Restore-WindowsAgentUpgrade.ps1"; DestDir: "{app}\Installer"; Flags: ignoreversion
Source: "..\scripts\Check-WindowsAgentHealth.ps1"; Flags: dontcopy
Source: "..\scripts\Set-WindowsHubAddress.ps1"; DestDir: "{app}\Installer"; Flags: ignoreversion
Source: "..\publish\hub-discovery\ComputerHost.HubDiscovery.exe"; Flags: dontcopy
Source: "CONNECT-TO-SMARTTHINGS.html"; DestDir: "{app}\Docs"; Flags: ignoreversion
Source: "..\..\docs\beta\THIRD-PARTY-NOTICES.md"; DestDir: "{app}\Docs"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\Computer Host LAN\Connect to SmartThings"; Filename: "{app}\Docs\CONNECT-TO-SMARTTHINGS.html"

[UninstallRun]
; Remove only our service and firewall; Inno removes tracked files. State
; intentionally survives uninstall in ProgramData for a later reinstallation.
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File ""{app}\Installer\Uninstall-WindowsAgent.ps1"" -KeepProgramFiles"; Flags: runhidden waituntilterminated 64bit; RunOnceId: ComputerHostAgentServiceCleanup

[Code]
// The UI stays in the installer, while service, firewall, identity and key
// management continue to use the existing supported PowerShell scripts.
// Never log, pass on a command line, or persist the 64-hex control token.
const
  ChannelURL = 'https://bestow-regional.api.smartthings.com/invite/1J2Qy7ZkxL20';
  WM_COPY = $0301;
  EM_SETPASSWORDCHAR = $00CC;
  EM_GETPASSWORDCHAR = $00D2;

var
  HubPage, PowerPage, ConnectPage, KeyPage: TWizardPage;
  HubSelect: TNewComboBox;
  HubStatus, LocalHelp: TNewStaticText;
  LocalSubnetCheck: TNewCheckBox;
  AdvancedButton: TNewButton;
  PowerCheck: TNewCheckBox;
  AgentStatus, DriverHint, DeviceHint, LinkCopyStatus, KeyHint, KeySetupHint, CopyStatus: TNewStaticText;
  OpenChannelButton, CopyLinkButton, ShowKeyButton, CopyKeyButton: TNewButton;
  LinkEdit, KeyEdit: TNewEdit;
  Searched, InstallFailed, AgentHealthy, UpgradePrepared, InstallCommitted: Boolean;

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
      if (Length(Part) > 1) and (Part[1] = '0') then Exit;
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

function ValidControlKey(const Value: String): Boolean;
var
  I: Integer;
begin
  Result := False;
  if Length(Value) <> 64 then Exit;
  for I := 1 to Length(Value) do
    if Pos(Value[I], '0123456789abcdefABCDEF') = 0 then Exit;
  Result := True;
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

procedure SetAdvancedVisible(const ShowAdvanced: Boolean);
begin
  LocalSubnetCheck.Visible := ShowAdvanced;
  LocalHelp.Visible := ShowAdvanced;
  if ShowAdvanced then
    AdvancedButton.Caption := 'Advanced options (hide)'
  else
    AdvancedButton.Caption := 'Advanced options';
end;

procedure ToggleAdvanced(Sender: TObject);
begin
  SetAdvancedVisible(not LocalSubnetCheck.Visible);
end;

procedure ChangeSubnetScope(Sender: TObject);
begin
  // A broader firewall scope is never activated silently. The user must
  // explicitly choose it (or pass /LOCALSUBNET=1 for unattended deployment).
  HubSelect.Enabled := not LocalSubnetCheck.Checked;
end;

procedure SearchForHubs(Sender: TObject);
var
  ExitCode, I, Sep, Count: Integer;
  FileName, Address, PreviousInput: String;
  Lines: TArrayOfString;
begin
  Searched := True;
  PreviousInput := HubSelect.Text;
  HubStatus.Caption := 'Searching for SmartThings hubs on your network...';
  // Initial discovery starts before the new page necessarily has time to
  // paint. Force the status and controls to render before blocking on the
  // external discovery helper. Keep search behavior and network scope intact.
  WizardForm.Repaint;
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
      HubStatus.Caption := 'Discovery unavailable. Enter the hub address or use the local-network option below.';
      if IsValidIPv4(PreviousInput) then HubSelect.Text := PreviousInput;
      SetAdvancedVisible(True);
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
      HubSelect.Enabled := True;
      SetAdvancedVisible(False);
      HubStatus.Caption := 'Hub found. Its IP address is already selected; click Next to continue.';
    end
    else if Count > 1 then
    begin
      LocalSubnetCheck.Checked := False;
      HubSelect.Enabled := True;
      SetAdvancedVisible(False);
      HubStatus.Caption := 'Several hubs found. Choose the one you want to use.';
    end
    else
    begin
      if IsValidIPv4(PreviousInput) then HubSelect.Text := PreviousInput;
      SetAdvancedVisible(True);
      HubStatus.Caption := 'No hub detected. Enter its IP address, or use the local-network option below.';
    end;
  except
    if IsValidIPv4(PreviousInput) then HubSelect.Text := PreviousInput;
    SetAdvancedVisible(True);
    HubStatus.Caption := 'Discovery unavailable. Enter the hub address or choose the local-network option.';
  end;
end;

procedure OpenChannel(Sender: TObject);
var
  ErrorCode: Integer;
begin
  if not ShellExecAsOriginalUser('', ChannelURL, '', '', SW_SHOWNORMAL, ewNoWait, ErrorCode) then
    if not ShellExec('', ChannelURL, '', '', SW_SHOWNORMAL, ewNoWait, ErrorCode) then
      MsgBox('Could not open the browser. Copy the channel invitation link instead.', mbInformation, MB_OK);
end;

procedure CopyLink(Sender: TObject);
begin
  LinkEdit.SelectAll;
  SendMessage(LinkEdit.Handle, WM_COPY, 0, 0);
  LinkCopyStatus.Caption := 'Invitation link copied.';
end;

// The native Win32 edit control may use a bullet for an ES_PASSWORD field
// even when TNewEdit.PasswordChar reports '*'. Always ask the window itself
// and explicitly set the native password mask on show, hide and copy.
procedure SetNativeKeyMask(const Mask: Integer);
begin
  SendMessage(KeyEdit.Handle, EM_SETPASSWORDCHAR, Mask, 0);
end;

procedure ShowOrHideKey(Sender: TObject);
begin
  if SendMessage(KeyEdit.Handle, EM_GETPASSWORDCHAR, 0, 0) <> 0 then
  begin
    KeyEdit.PasswordChar := #0;
    SetNativeKeyMask(0);
    ShowKeyButton.Caption := 'Hide key';
  end
  else
  begin
    KeyEdit.PasswordChar := '*';
    SetNativeKeyMask(Ord('*'));
    ShowKeyButton.Caption := 'Show key';
  end;
end;

procedure CopySecretKey(Sender: TObject);
var
  PreviousMask: Integer;
begin
  if not ValidControlKey(KeyEdit.Text) then Exit;
  // Native password edit controls refuse WM_COPY when masking is active.
  // Temporarily remove the mask only for an explicit user click, and
  // reliably restore the exact previous native character even on failure.
  PreviousMask := SendMessage(KeyEdit.Handle, EM_GETPASSWORDCHAR, 0, 0);
  try
    KeyEdit.PasswordChar := #0;
    SetNativeKeyMask(0);
    KeyEdit.SelectAll;
    SendMessage(KeyEdit.Handle, WM_COPY, 0, 0);
  finally
    if PreviousMask <> 0 then
    begin
      KeyEdit.PasswordChar := '*';
      SetNativeKeyMask(PreviousMask);
    end
    else
    begin
      KeyEdit.PasswordChar := #0;
      SetNativeKeyMask(0);
    end;
  end;
  CopyStatus.Caption := 'Key copied. Paste it into your SmartThings device settings.';
end;

function LoadPrivateKey: Boolean;
var
  Contents: AnsiString;
  Token: String;
begin
  Result := False;
  // Only an elevated installer can access the LocalService-protected key
  // directory. Never log its content, even when retrieval fails.
  if not LoadStringFromFile(ExpandConstant('{commonappdata}\ComputerHostAgent\control-token'), Contents) then
    Exit;
  Token := Trim(String(Contents));
  if not ValidControlKey(Token) then Exit;
  KeyEdit.Text := Token;
  Result := True;
end;

// Match a customized HTTP port retained during upgrade; the installer
// PowerShell script validates the same configured port before service start.
function AgentPort: Integer;
var
  Raw: AnsiString;
  Config, Value: String;
  Position, I, Parsed: Integer;
begin
  Result := 8765;
  if not LoadStringFromFile(ExpandConstant('{app}\appsettings.json'), Raw) then Exit;
  Config := LowerCase(String(Raw));
  StringChangeEx(Config, ' ', '', True);
  StringChangeEx(Config, #13, '', True);
  StringChangeEx(Config, #10, '', True);
  StringChangeEx(Config, #9, '', True);
  Position := Pos('"port":', Config);
  if Position = 0 then Exit;
  Position := Position + Length('"port":');
  Value := '';
  for I := Position to Length(Config) do
  begin
    if (Config[I] < '0') or (Config[I] > '9') then Break;
    Value := Value + Config[I];
  end;
  Parsed := StrToIntDef(Value, 8765);
  if (Parsed >= 1024) and (Parsed <= 65535) then Result := Parsed;
end;

// Restore original application files, firewall and service if the install
// fails after the preflight snapshot. Commit removes the snapshot on success.
function FinishUpgrade(const Mode: String): Boolean;
var
  ExitCode: Integer;
  Params: String;
begin
  Result := True;
  if not UpgradePrepared then Exit;
  ExtractTemporaryFile('Restore-WindowsAgentUpgrade.ps1');
  Params := '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' +
    ExpandConstant('{tmp}\Restore-WindowsAgentUpgrade.ps1') + '" -Mode ' + Mode;
  Result := ExecWithNativeSysDir(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
    Params, '', SW_HIDE, ewWaitUntilTerminated, ExitCode) and (ExitCode = 0);
  if not Result then Log('Upgrade ' + Mode + ' failed; inspect the admin-protected rollback snapshot.');
end;

procedure ShowConnectionPage;
var
  ResultCode, I: Integer;
begin
  // No host identifier or key appears in the result or in installer logs.
  AgentHealthy := False;
  for I := 1 to 5 do
  begin
    if Exec(ExpandConstant('{sys}\curl.exe'),
      '--fail --silent --output NUL --max-time 3 http://127.0.0.1:' + IntToStr(AgentPort()) + '/v2/health',
      '', SW_HIDE, ewWaitUntilTerminated, ResultCode) and (ResultCode = 0) then
    begin
      AgentHealthy := True;
      Break;
    end;
    Sleep(400);
  end;
  if AgentHealthy then
    AgentStatus.Caption := 'Computer Host Agent is running and responding.'
  else
    AgentStatus.Caption := 'The agent is installed but is not responding yet. Check the service or try the setup guide.';

  LinkCopyStatus.Caption := 'You can reopen these instructions later from the Start Menu.';
end;

procedure ShowPrivateKeyPage;
begin
  KeyEdit.Visible := False;
  ShowKeyButton.Visible := False;
  CopyKeyButton.Visible := False;
  if LoadPrivateKey then
  begin
    KeyHint.Caption := 'Your private authentication key:';
    KeyEdit.Visible := True;
    ShowKeyButton.Visible := True;
    CopyKeyButton.Visible := True;
    KeyEdit.PasswordChar := '*';
    SetNativeKeyMask(Ord('*'));
    ShowKeyButton.Caption := 'Show key';
  end
  else
    KeyHint.Caption := 'The power-control key could not be retrieved. See the setup guide.';
  CopyStatus.Caption := 'Keep this key private. Never share it in logs or forum posts.';
end;

procedure InitializeWizard;
var
  LabelText, PowerText: TNewStaticText;
  SearchButton: TNewButton;
  SilentHub: String;
begin
  HubPage := CreateCustomPage(wpWelcome, 'SmartThings hub', 'Find the hub on your local network');
  LabelText := TNewStaticText.Create(HubPage);
  LabelText.Parent := HubPage.Surface;
  LabelText.Caption := 'SmartThings hub IPv4 (DHCP reservation recommended):';
  LabelText.Top := ScaleY(4);

  HubSelect := TNewComboBox.Create(HubPage);
  HubSelect.Parent := HubPage.Surface;
  HubSelect.Left := 0;
  HubSelect.Top := LabelText.Top + LabelText.Height + ScaleY(6);
  // Size relative to the actual wizard surface. Fixed widths previously
  // risked clipping the address field on compact/scaled displays or Wine.
  HubSelect.Width := HubPage.SurfaceWidth - ScaleX(126);
  HubSelect.Height := ScaleY(23);
  HubSelect.Style := csDropDown;

  SearchButton := TNewButton.Create(HubPage);
  SearchButton.Parent := HubPage.Surface;
  SearchButton.Caption := 'Search again';
  SearchButton.Left := HubSelect.Width + ScaleX(8);
  SearchButton.Top := HubSelect.Top;
  SearchButton.Width := HubPage.SurfaceWidth - SearchButton.Left;
  SearchButton.Height := ScaleY(23);
  SearchButton.OnClick := @SearchForHubs;

  HubStatus := TNewStaticText.Create(HubPage);
  HubStatus.Parent := HubPage.Surface;
  HubStatus.Top := HubSelect.Top + HubSelect.Height + ScaleY(12);
  HubStatus.Width := HubPage.SurfaceWidth;
  HubStatus.AutoSize := False;
  HubStatus.Height := ScaleY(42);
  HubStatus.WordWrap := True;
  HubStatus.Caption := 'The installer will look for SmartThings hubs when this page opens.';

  AdvancedButton := TNewButton.Create(HubPage);
  AdvancedButton.Parent := HubPage.Surface;
  AdvancedButton.Top := HubStatus.Top + HubStatus.Height + ScaleY(5);
  AdvancedButton.Width := ScaleX(154);
  AdvancedButton.Height := ScaleY(24);
  AdvancedButton.OnClick := @ToggleAdvanced;

  LocalSubnetCheck := TNewCheckBox.Create(HubPage);
  LocalSubnetCheck.Parent := HubPage.Surface;
  LocalSubnetCheck.Top := AdvancedButton.Top + AdvancedButton.Height + ScaleY(10);
  LocalSubnetCheck.Width := HubPage.SurfaceWidth;
  LocalSubnetCheck.Height := ScaleY(22);
  LocalSubnetCheck.Caption := 'Allow connections from devices on my local network';
  LocalSubnetCheck.Checked := False;
  LocalSubnetCheck.OnClick := @ChangeSubnetScope;

  LocalHelp := TNewStaticText.Create(HubPage);
  LocalHelp.Parent := HubPage.Surface;
  LocalHelp.Top := LocalSubnetCheck.Top + LocalSubnetCheck.Height + ScaleY(4);
  LocalHelp.Width := HubPage.SurfaceWidth;
  LocalHelp.Height := ScaleY(44);
  LocalHelp.AutoSize := False;
  LocalHelp.WordWrap := True;
  LocalHelp.Caption := 'Use this option if your SmartThings hub cannot be detected automatically and you do not know its IP address.';
  SetAdvancedVisible(False);

  PowerPage := CreateCustomPage(HubPage.ID, 'Power management', 'Optional shutdown, reboot and suspend');
  PowerText := TNewStaticText.Create(PowerPage);
  PowerText.Parent := PowerPage.Surface;
  PowerText.Width := PowerPage.SurfaceWidth;
  PowerText.AutoSize := False;
  PowerText.Height := ScaleY(60);
  PowerText.WordWrap := True;
  PowerText.Caption := 'Computer Host LAN can monitor your PC without controlling its power. Enable the option below only if you also want SmartThings to request graceful shutdown, restart and suspend.';

  PowerCheck := TNewCheckBox.Create(PowerPage);
  PowerCheck.Parent := PowerPage.Surface;
  PowerCheck.Top := PowerText.Top + PowerText.Height + ScaleY(16);
  PowerCheck.Width := PowerPage.SurfaceWidth;
  PowerCheck.Height := ScaleY(22);
  PowerCheck.Caption := 'Enable authenticated shutdown, reboot and suspend';
  PowerCheck.Checked := WasPowerEnabled();

  PowerText := TNewStaticText.Create(PowerPage);
  PowerText.Parent := PowerPage.Surface;
  PowerText.Width := PowerPage.SurfaceWidth;
  PowerText.Top := PowerCheck.Top + PowerCheck.Height + ScaleY(12);
  PowerText.Height := ScaleY(55);
  PowerText.WordWrap := True;
  PowerText.AutoSize := False;
  PowerText.Caption := 'Upgrades keep your existing power-control setting. The key is available after installation.';

  // This page appears only after files and service installation are complete.
  ConnectPage := CreateCustomPage(wpInstalling, 'Connect to SmartThings', 'Complete setup in the SmartThings app');

  AgentStatus := TNewStaticText.Create(ConnectPage);
  AgentStatus.Parent := ConnectPage.Surface;
  AgentStatus.Width := ConnectPage.SurfaceWidth;
  AgentStatus.AutoSize := False;
  AgentStatus.WordWrap := True;
  AgentStatus.Height := ScaleY(33);

  OpenChannelButton := TNewButton.Create(ConnectPage);
  OpenChannelButton.Parent := ConnectPage.Surface;
  OpenChannelButton.Caption := 'Open driver channel';
  OpenChannelButton.Top := AgentStatus.Top + AgentStatus.Height + ScaleY(4);
  OpenChannelButton.Width := ScaleX(168);
  OpenChannelButton.Height := ScaleY(25);
  OpenChannelButton.OnClick := @OpenChannel;

  CopyLinkButton := TNewButton.Create(ConnectPage);
  CopyLinkButton.Parent := ConnectPage.Surface;
  CopyLinkButton.Caption := 'Copy invitation link';
  CopyLinkButton.Left := OpenChannelButton.Width + ScaleX(8);
  CopyLinkButton.Top := OpenChannelButton.Top;
  CopyLinkButton.Width := ConnectPage.SurfaceWidth - CopyLinkButton.Left;
  CopyLinkButton.Height := ScaleY(25);
  CopyLinkButton.OnClick := @CopyLink;

  LinkEdit := TNewEdit.Create(ConnectPage);
  LinkEdit.Parent := ConnectPage.Surface;
  LinkEdit.Left := 0;
  LinkEdit.Width := ConnectPage.SurfaceWidth;
  LinkEdit.Top := OpenChannelButton.Top + OpenChannelButton.Height + ScaleY(5);
  LinkEdit.Height := ScaleY(23);
  LinkEdit.ReadOnly := True;
  LinkEdit.Text := ChannelURL;

  DriverHint := TNewStaticText.Create(ConnectPage);
  DriverHint.Parent := ConnectPage.Surface;
  DriverHint.Top := LinkEdit.Top + LinkEdit.Height + ScaleY(6);
  DriverHint.Width := ConnectPage.SurfaceWidth;
  DriverHint.AutoSize := False;
  DriverHint.WordWrap := True;
  DriverHint.Height := ScaleY(34);
  DriverHint.Caption := '1. Sign in, accept the invitation, enroll your hub and install Computer Host LAN under Available Drivers.';

  DeviceHint := TNewStaticText.Create(ConnectPage);
  DeviceHint.Parent := ConnectPage.Surface;
  DeviceHint.Top := DriverHint.Top + DriverHint.Height + ScaleY(4);
  DeviceHint.Width := ConnectPage.SurfaceWidth;
  DeviceHint.AutoSize := False;
  DeviceHint.Height := ScaleY(28);
  DeviceHint.WordWrap := True;
  DeviceHint.Caption := '2. In the SmartThings app choose Add device > Scan nearby. Existing users can keep their device.';

  LinkCopyStatus := TNewStaticText.Create(ConnectPage);
  LinkCopyStatus.Parent := ConnectPage.Surface;
  LinkCopyStatus.Top := DeviceHint.Top + DeviceHint.Height + ScaleY(8);
  LinkCopyStatus.Width := ConnectPage.SurfaceWidth;
  LinkCopyStatus.AutoSize := False;
  LinkCopyStatus.WordWrap := True;
  LinkCopyStatus.Height := ScaleY(42);
  LinkCopyStatus.Caption := 'You can reopen these instructions later from the Start Menu.';

  // Power users get an additional post-install page. Monitoring-only users
  // never see a blank key page; this keeps the default setup compact.
  KeyPage := CreateCustomPage(ConnectPage.ID, 'Power control key',
    'Copy the private key into your SmartThings device settings');

  KeyHint := TNewStaticText.Create(KeyPage);
  KeyHint.Parent := KeyPage.Surface;
  KeyHint.Top := ScaleY(6);
  KeyHint.Width := KeyPage.SurfaceWidth;
  KeyHint.AutoSize := False;
  KeyHint.WordWrap := True;
  KeyHint.Height := ScaleY(36);
  KeyHint.Caption := 'Your private authentication key:';

  KeyEdit := TNewEdit.Create(KeyPage);
  KeyEdit.Parent := KeyPage.Surface;
  KeyEdit.Top := KeyHint.Top + KeyHint.Height + ScaleY(5);
  KeyEdit.Width := KeyPage.SurfaceWidth;
  KeyEdit.Height := ScaleY(23);
  KeyEdit.ReadOnly := True;
  KeyEdit.PasswordChar := '*';

  ShowKeyButton := TNewButton.Create(KeyPage);
  ShowKeyButton.Parent := KeyPage.Surface;
  ShowKeyButton.Top := KeyEdit.Top + KeyEdit.Height + ScaleY(8);
  ShowKeyButton.Caption := 'Show key';
  ShowKeyButton.Width := ScaleX(120);
  ShowKeyButton.Height := ScaleY(25);
  ShowKeyButton.OnClick := @ShowOrHideKey;

  CopyKeyButton := TNewButton.Create(KeyPage);
  CopyKeyButton.Parent := KeyPage.Surface;
  CopyKeyButton.Top := ShowKeyButton.Top;
  CopyKeyButton.Left := ShowKeyButton.Width + ScaleX(8);
  CopyKeyButton.Caption := 'Copy authentication key';
  CopyKeyButton.Width := KeyPage.SurfaceWidth - CopyKeyButton.Left;
  CopyKeyButton.Height := ScaleY(25);
  CopyKeyButton.OnClick := @CopySecretKey;

  KeySetupHint := TNewStaticText.Create(KeyPage);
  KeySetupHint.Parent := KeyPage.Surface;
  KeySetupHint.Top := CopyKeyButton.Top + CopyKeyButton.Height + ScaleY(13);
  KeySetupHint.Width := KeyPage.SurfaceWidth;
  KeySetupHint.AutoSize := False;
  KeySetupHint.WordWrap := True;
  KeySetupHint.Height := ScaleY(53);
  KeySetupHint.Caption :=
    'Open the computer device settings in SmartThings, enable shutdown/reboot/suspend, and paste this key into Power control key (64 hex chars).';

  CopyStatus := TNewStaticText.Create(KeyPage);
  CopyStatus.Parent := KeyPage.Surface;
  CopyStatus.Width := KeyPage.SurfaceWidth;
  CopyStatus.Top := KeySetupHint.Top + KeySetupHint.Height + ScaleY(12);
  CopyStatus.AutoSize := False;
  CopyStatus.WordWrap := True;
  CopyStatus.Height := ScaleY(33);
  CopyStatus.Caption := 'Keep this key private. Never share it in logs or forum posts.';

  SilentHub := ExpandConstant('{param:HUBIP|}');
  if SilentHub <> '' then
  begin
    HubSelect.Text := SilentHub;
    HubStatus.Caption := 'Using the supplied hub IP address. You can change it if necessary.';
  end;
  if ExpandConstant('{param:LOCALSUBNET|0}') = '1' then
  begin
    LocalSubnetCheck.Checked := True;
    HubSelect.Enabled := False;
    SetAdvancedVisible(True);
  end;
  if ExpandConstant('{param:ENABLEPOWER|}') <> '' then
    PowerCheck.Checked := ExpandConstant('{param:ENABLEPOWER|0}') = '1';
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if (CurPageID = HubPage.ID) and (not Searched) and (not WizardSilent) and
     (HubSelect.Text = '') then
  begin
    // CurPageChanged runs as the page becomes active; without this repaint,
    // waiting for the discovery process can leave the title/controls half drawn.
    WizardForm.Repaint;
    SearchForHubs(nil);
  end;
  if (CurPageID = ConnectPage.ID) and not WizardSilent and not InstallFailed then
    ShowConnectionPage;
  if (CurPageID = KeyPage.ID) and not WizardSilent and not InstallFailed then
    ShowPrivateKeyPage;
  if CurPageID = wpFinished then
  begin
    if InstallFailed then
    begin
      WizardForm.FinishedHeadingLabel.Caption := 'Installation needs attention';
      WizardForm.FinishedLabel.Caption := 'The Computer Host Agent service could not be configured. Review the setup log and retry.';
    end
    else
    begin
      WizardForm.FinishedHeadingLabel.Caption := 'Computer Host LAN is installed';
      if AgentHealthy then
        WizardForm.FinishedLabel.Caption :=
          'Computer Host Agent is running and responding. You can open the Connect to SmartThings guide again from the Start Menu.'
      else
        WizardForm.FinishedLabel.Caption :=
          'The Windows service was installed but is not responding yet. Check its status and use the Start Menu setup guide to continue.';
    end;
  end;
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := (PageID = KeyPage.ID) and
    (not PowerCheck.Checked or InstallFailed or WizardSilent);
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
  if (CurPageID = HubPage.ID) and not ValidConfiguration then
  begin
    MsgBox('Select or enter your SmartThings hub IP address, or use Advanced options to allow local-network access.',
      mbError, MB_OK);
    Result := False;
  end;
end;

// Explicitly offer recovery from an abandoned snapshot before touching the agent.
// A silent installation refuses this situation instead of changing user state.
function RecoverAbandonedSnapshot: Boolean;
var
  Snapshot, Params: String;
  ExitCode: Integer;
begin
  Result := True;
  Snapshot := ExpandConstant('{autopf}\Computer Host Agent.upgrade-rollback');
  if not DirExists(Snapshot) then Exit;
  Result := False;
  if WizardSilent then Exit;
  if MsgBox('An unfinished Computer Host LAN upgrade was detected. Restore the previous installation before proceeding?',
    mbConfirmation, MB_YESNO) <> IDYES then Exit;
  ExtractTemporaryFile('Restore-WindowsAgentUpgrade.ps1');
  Params := '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' +
    ExpandConstant('{tmp}\Restore-WindowsAgentUpgrade.ps1') + '" -Mode Restore';
  Result := ExecWithNativeSysDir(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
    Params, '', SW_HIDE, ewWaitUntilTerminated, ExitCode) and (ExitCode = 0);
  if not Result then MsgBox('Recovery could not be completed. Preserve the rollback snapshot and consult the release recovery instructions.',
    mbError, MB_OK);
end;

// Require a healthy new agent before removing the last known-good snapshot.
function CheckAgentBeforeCommit: Boolean;
var
  ExitCode: Integer;
  Params: String;
begin
  ExtractTemporaryFile('Check-WindowsAgentHealth.ps1');
  Params := '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' +
    ExpandConstant('{tmp}\Check-WindowsAgentHealth.ps1') + '" -ExpectedVersion 0.2.5-beta.1';
  Result := ExecWithNativeSysDir(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
    Params, '', SW_HIDE, ewWaitUntilTerminated, ExitCode) and (ExitCode = 0);
  if not Result then Log('Agent health/identity/version gate failed before committing upgrade.');
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ExitCode: Integer;
  Params, DiagnosticFile: String;
  Details: AnsiString;
begin
  Result := '';
  if not ValidConfiguration then
  begin
    Result := 'Missing hub address. Use /HUBIP=192.168.1.20 or /LOCALSUBNET=1 in silent mode.';
    Exit;
  end;
  if not RecoverAbandonedSnapshot then
  begin
    Result := 'A previous upgrade requires restoration before proceeding. Existing service was not modified. Use interactive recovery or the recovery script from the Windows ZIP.';
    Exit;
  end;
  ExtractTemporaryFile('Prepare-WindowsAgentUpgrade.ps1');
  DiagnosticFile := ExpandConstant('{tmp}\computerhost-preparation-error.txt');
  DeleteFile(DiagnosticFile);
  Params := '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' +
    ExpandConstant('{tmp}\Prepare-WindowsAgentUpgrade.ps1') + '" -DiagnosticPath "' +
    DiagnosticFile + '"';
  if not ExecWithNativeSysDir(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
    Params, '', SW_HIDE, ewWaitUntilTerminated, ExitCode) or (ExitCode <> 0) then
  begin
    Result := 'Unable to stop or validate the existing Computer Host Agent service. ' +
      'No application files were replaced.';
    if LoadStringFromFile(DiagnosticFile, Details) then
    begin
      Log(String(Details));
      Result := Result + ' ' + String(Details);
    end;
  end
  else
    UpgradePrepared := True;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Params, DiagnosticFile, FailureMessage: String;
  ExitCode: Integer;
  Details: AnsiString;
begin
  if CurStep <> ssPostInstall then Exit;
  DiagnosticFile := ExpandConstant('{tmp}\computerhost-service-installation.txt');
  DeleteFile(DiagnosticFile);
  Params := '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' +
    ExpandConstant('{app}\Installer\Install-WindowsAgent.ps1') +
    '" -PublishedDirectory "' + ExpandConstant('{app}') +
    '" -UseExistingFiles -DiagnosticPath "' + DiagnosticFile + '"';
  if not LocalSubnetCheck.Checked then
    Params := Params + ' -HubIPv4 ' + SelectedHubIP;
  if PowerCheck.Checked then Params := Params + ' -EnablePower';
  if not ExecWithNativeSysDir(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
    Params, '', SW_HIDE, ewWaitUntilTerminated, ExitCode) or (ExitCode <> 0) then
  begin
    InstallFailed := True;
    FailureMessage := 'Computer Host Agent service installation failed. Review the setup log and retry.';
    if LoadStringFromFile(DiagnosticFile, Details) then
    begin
      Log(String(Details));
      FailureMessage := FailureMessage + ' ' + String(Details);
    end;
    Log(FailureMessage);
    if not WizardSilent then MsgBox(FailureMessage, mbError, MB_OK);
    FinishUpgrade('Restore');
  end
  else
  begin
    if not CheckAgentBeforeCommit then
    begin
      InstallFailed := True;
      FinishUpgrade('Restore');
    end
    else if FinishUpgrade('Commit') then InstallCommitted := True
    else
    begin
      InstallFailed := True;
      FinishUpgrade('Restore');
    end;
  end;
end;

function GetCustomSetupExitCode: Integer;
begin
  if InstallFailed then Result := 17 else Result := 0;
end;

// Inno's [UninstallRun] action cannot veto tracked file removal when a
// service-cleanup script refuses a hijacked service. Validate ownership
// BEFORE starting Uninstall so executable files are never removed while
// an unexpected service with our name is still registered.
function InitializeUninstall: Boolean;
var
  ScriptPath, Params: String;
  ExitCode: Integer;
begin
  Result := False;
  ScriptPath := ExpandConstant('{app}\Installer\Uninstall-WindowsAgent.ps1');
  if FileExists(ScriptPath) then
  begin
    Params := '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' +
      ScriptPath + '" -ValidateOnly';
    if ExecWithNativeSysDir(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
      Params, '', SW_HIDE, ewWaitUntilTerminated, ExitCode) and (ExitCode = 0) then
      Result := True;
  end;
  if not Result then
  begin
    Log('Uninstall blocked: ComputerHostAgent service ownership validation failed or cleanup script is missing.');
    if not UninstallSilent then
      MsgBox('Computer Host LAN cannot safely uninstall because the service ' +
        'does not match this installation, or its cleanup script is missing. ' +
        'No files have been removed. See the setup documentation.',
        mbError, MB_OK);
  end;
end;

procedure DeinitializeSetup;
begin
  // Also cover a cancelled or interrupted upgrade before ssPostInstall.
  if UpgradePrepared and not InstallCommitted then FinishUpgrade('Restore');
  // Do not leave the key in a UI field after the wizard closes.
  if KeyEdit <> nil then KeyEdit.Text := '';
end;
