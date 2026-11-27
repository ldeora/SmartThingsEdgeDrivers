; Computer Host LAN — unsigned Windows graphical installer.
; Reuses the existing ZIP installer scripts; never modifies ProgramData state.
; Native Windows CI tested; hub discovery and power behavior require physical hardware verification.
#define IntegrationVersion "1.0.0-rc.3"
; Must match release.json windows_agent; both CI and Python version tests enforce this.
#define WindowsAgentVersion "0.2.8-rc.3"
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
; Extract the small inspection script before the solid-compressed payload.
Source: "..\scripts\Install-WindowsAgent.ps1"; DestDir: "{app}\Installer"; Flags: ignoreversion
; Inno owns Program Files; the PowerShell script reuses already-installed files.
; Preserve existing host-side settings on ZIP-to-Setup and Setup-to-Setup upgrades.
; The PowerShell service installer updates only EnablePowerControl after copy.
Source: "..\publish\win-x64\*"; DestDir: "{app}"; Excludes: "appsettings.json"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\publish\win-x64\appsettings.json"; DestDir: "{app}"; Flags: onlyifdoesntexist
Source: "..\scripts\Uninstall-WindowsAgent.ps1"; DestDir: "{app}\Installer"; Flags: ignoreversion
Source: "..\scripts\Prepare-WindowsAgentUpgrade.ps1"; Flags: dontcopy
Source: "..\scripts\Restore-WindowsAgentUpgrade.ps1"; Flags: dontcopy
Source: "..\scripts\Restore-WindowsAgentUpgrade.ps1"; DestDir: "{app}\Installer"; Flags: ignoreversion
Source: "..\scripts\Check-WindowsAgentHealth.ps1"; Flags: dontcopy
Source: "..\scripts\Set-WindowsHubAddress.ps1"; DestDir: "{app}\Installer"; Flags: ignoreversion
Source: "..\publish\hub-discovery\ComputerHost.HubDiscovery.exe"; Flags: dontcopy
Source: "CONNECT-TO-SMARTTHINGS.html"; DestDir: "{app}\Docs"; Flags: ignoreversion
Source: "..\..\LICENSE"; DestDir: "{app}\Docs"; Flags: ignoreversion
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
  UpgradePage, HubPage, PowerPage, ConnectPage, KeyPage: TWizardPage;
  UpgradeSummary, UpgradeDeviceHint: TNewStaticText;
  ChangeSettingsCheck, ConfirmPowerCheck: TNewCheckBox;
  PreviousScope: String;
  PreviousPower, ExplicitScope, ExplicitPower, ShowUpgradeSummary: Boolean;
  ScopeConfirmed, PowerConfirmed, InstallWasUpgrade, RetainedPowerKey, SnapshotRecovered: Boolean;
  HubSelect: TNewComboBox;
  HubStatus, HubTip, LocalHelp, NetworkProfileHint, PowerNote, WolHint: TNewStaticText;
  HubStatusBase, HubStatusPrefix: String;
  HubStatusShowsSelection: Boolean;
  LocalSubnetCheck: TNewCheckBox;
  AdvancedButton: TNewButton;
  PowerCheck: TNewCheckBox;
  AgentStatus, DriverHint, DeviceHint, LinkCopyStatus, KeyHint, KeySetupHint, CopyStatus: TNewStaticText;
  OpenChannelButton, CopyLinkButton, ShowKeyButton, CopyKeyButton: TNewButton;
  LinkEdit, KeyEdit: TNewEdit;
  Searched, InstallFailed, AgentHealthy, UpgradePrepared, InstallCommitted: Boolean;
  ExistingInstallation, InspectionFailed, InvalidArguments: Boolean;

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

// Ask the same PowerShell implementation used by the ZIP installer.
procedure InspectPreviousConfiguration(var Scope: String; var Power: Boolean);
var
  ExitCode, FirstSep, SecondSep: Integer;
  FileName, DiagnosticFile, Params, Reply, Kind, PowerValue: String;
  Raw, Details: AnsiString;
begin
  Scope := 'unknown';
  Power := False;
  InspectionFailed := True;
  try
    ExtractTemporaryFile('Install-WindowsAgent.ps1');
    FileName := ExpandConstant('{tmp}\computerhost-configuration.txt');
    DiagnosticFile := ExpandConstant('{tmp}\computerhost-inspect-error.txt');
    DeleteFile(FileName);
    DeleteFile(DiagnosticFile);
    Params := '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' +
      ExpandConstant('{tmp}\Install-WindowsAgent.ps1') +
      '" -InspectConfiguration -ConfigurationPath "' + FileName +
      '" -DiagnosticPath "' + DiagnosticFile + '"';
    if not ExecWithNativeSysDir(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
      Params, '', SW_HIDE, ewWaitUntilTerminated, ExitCode) then
    begin
      Log('Configuration inspection: PowerShell could not be launched (' + IntToStr(ExitCode) + ').');
      Exit;
    end;
    if ExitCode <> 0 then
    begin
      Log('Configuration inspection: PowerShell returned ' + IntToStr(ExitCode) + '.');
      if LoadStringFromFile(DiagnosticFile, Details) then Log(String(Details))
      else Log('Configuration inspection: no script diagnostic available.');
      Exit;
    end;
    if not LoadStringFromFile(FileName, Raw) then
    begin
      Log('Configuration inspection: response file missing or unreadable.');
      Exit;
    end;
    Reply := Trim(String(Raw));
    FirstSep := Pos('|', Reply);
    if FirstSep > 0 then
    begin
      Kind := Copy(Reply, 1, FirstSep - 1);
      Delete(Reply, 1, FirstSep);
    end;
    SecondSep := Pos('|', Reply);
    if (FirstSep = 0) or (SecondSep = 0) then
    begin
      Log('Configuration inspection: wrong field count.');
      Exit;
    end;
    PowerValue := Copy(Reply, 1, SecondSep - 1);
    Delete(Reply, 1, SecondSep);
    if Pos('|', Reply) > 0 then
    begin
      Log('Configuration inspection: wrong field count.');
      Exit;
    end;
    if ((Kind <> 'upgrade') and (Kind <> 'fresh')) or
       ((PowerValue <> 'on') and (PowerValue <> 'off')) or
       ((Reply <> 'unknown') and (Reply <> 'LocalSubnet') and not IsValidIPv4(Reply)) then
    begin
      Log('Configuration inspection: unexpected response values.');
      Exit;
    end;
    ExistingInstallation := Kind = 'upgrade';
    Power := PowerValue = 'on';
    Scope := Reply;
    InspectionFailed := False;
    Log('Configuration inspection: succeeded.');
  except
    Log('Configuration inspection: exception while extracting, launching or reading response.');
    InspectionFailed := True;
  end;
end;

procedure SetAdvancedVisible(const ShowAdvanced: Boolean);
begin
  LocalSubnetCheck.Visible := ShowAdvanced;
  LocalHelp.Visible := ShowAdvanced;
  if ShowAdvanced then
    AdvancedButton.Caption := 'Hide advanced options'
  else
    AdvancedButton.Caption := 'Advanced options';
end;

// The hub status has two parts. HubStatusBase is what Setup found (search
// result, previous settings) and never names an address the user typed.
// Once the user changes the address or the local-network option, the shown
// text is recomputed from the current field and checkbox (RefreshHubStatus).
procedure SetHubStatus(const Text: String);
begin
  HubStatus.Caption := Text;
  HubStatusBase := Text;
  HubStatusPrefix := '';
  HubStatusShowsSelection := False;
end;

procedure ToggleAdvanced(Sender: TObject);
begin
  SetAdvancedVisible(not LocalSubnetCheck.Visible);
end;

// Normalise the visible dropdown label before either installation or retry.
// The same parser is used in SelectedHubIP so the two paths cannot diverge.
function HubIPv4FromSelection(const Selection: String): String;
var
  CutAt: Integer;
begin
  Result := Trim(Selection);
  CutAt := Pos(' (', Result);
  if CutAt > 0 then Result := Copy(Result, 1, CutAt - 1);
end;

procedure RefreshHubStatus;
var
  Address: String;
begin
  if not HubStatusShowsSelection then
    HubStatus.Caption := HubStatusBase
  else if LocalSubnetCheck.Checked then
    HubStatus.Caption := 'Local-network option selected: devices on this Private network can connect. No hub address is needed.'
  else
  begin
    Address := HubIPv4FromSelection(HubSelect.Text);
    if IsValidIPv4(Address) then
      HubStatus.Caption := HubStatusPrefix + 'Using ' + Address + '. Click Next to continue.'
    else
      HubStatus.Caption := HubStatusPrefix + 'Enter the hub''s IP address, use Search again, or choose the local-network option.';
  end;
end;

// Show the address kept after a search, prefixed with the search result.
procedure ShowEnteredHub(const Prefix: String);
begin
  HubStatusPrefix := Prefix;
  HubStatusShowsSelection := True;
  RefreshHubStatus;
end;

// Only user changes on the visible hub page switch the status to the
// current choice. Programmatic changes before the page opens keep it.
procedure HubChoiceChanged(Sender: TObject);
begin
  if WizardForm.CurPageID <> HubPage.ID then Exit;
  HubStatusShowsSelection := True;
  RefreshHubStatus;
end;

procedure ChangeSubnetScope(Sender: TObject);
begin
  // A broader firewall scope is never activated silently. The user must
  // explicitly choose it (or pass /LOCALSUBNET=1 for unattended deployment).
  HubSelect.Enabled := not LocalSubnetCheck.Checked;
  HubChoiceChanged(Sender);
end;

procedure SearchForHubs(Sender: TObject);
var
  ExitCode, I, Sep, Count: Integer;
  FileName, Address, PreviousInput: String;
  Lines: TArrayOfString;
begin
  Searched := True;
  // A discovered entry is displayed as "IPv4 (hub name)". Retain its
  // actual address on an unsuccessful retry rather than discarding it as
  // invalid input. This also preserves a manually entered IPv4 address.
  PreviousInput := HubIPv4FromSelection(HubSelect.Text);
  if not IsValidIPv4(PreviousInput) then PreviousInput := '';
  // Clear the field first: its change handler must not replace the
  // searching status while the discovery helper runs.
  HubSelect.Items.Clear;
  HubSelect.Text := '';
  SetHubStatus('Searching for SmartThings hubs on your network...');
  // Initial discovery starts before the new page necessarily has time to
  // paint. Force the status and controls to render before blocking on the
  // external discovery helper. Keep search behavior and network scope intact.
  WizardForm.Repaint;
  try
    ExtractTemporaryFile('ComputerHost.HubDiscovery.exe');
    FileName := ExpandConstant('{tmp}\smartthings-hubs.txt');
    DeleteFile(FileName);
    if not Exec(ExpandConstant('{tmp}\ComputerHost.HubDiscovery.exe'),
      '--output "' + FileName + '"', '', SW_HIDE, ewWaitUntilTerminated, ExitCode) or
      (ExitCode <> 0) or (not LoadStringsFromFile(FileName, Lines)) then
    begin
      SetHubStatus('Discovery unavailable. Enter the hub address or use the local-network option below.');
      if IsValidIPv4(PreviousInput) then
      begin
        HubSelect.Text := PreviousInput;
        ShowEnteredHub('Discovery unavailable. ');
      end;
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
    if (Count = 1) and not ExistingInstallation and not InspectionFailed then
    begin
      HubSelect.ItemIndex := 0;
      LocalSubnetCheck.Checked := False;
      HubSelect.Enabled := True;
      SetAdvancedVisible(False);
      SetHubStatus('Hub found. Its IP address is already selected; click Next to continue.');
    end
    else if Count > 0 then
    begin
      LocalSubnetCheck.Checked := False;
      HubSelect.Enabled := True;
      SetAdvancedVisible(False);
      HubSelect.ItemIndex := -1;
      HubSelect.Text := '';
      if IsValidIPv4(PreviousInput) then HubSelect.Text := PreviousInput;
      SetHubStatus('Choose the hub you want to use.');
    end
    else
    begin
      SetAdvancedVisible(True);
      SetHubStatus('No hub detected. Enter its IP address, or use the local-network option below.');
      if IsValidIPv4(PreviousInput) then
      begin
        HubSelect.Text := PreviousInput;
        ShowEnteredHub('No hub detected. ');
      end;
    end;
  except
    SetAdvancedVisible(True);
    SetHubStatus('Discovery unavailable. Enter the hub address or choose the local-network option.');
    if IsValidIPv4(PreviousInput) then
    begin
      HubSelect.Text := PreviousInput;
      ShowEnteredHub('Discovery unavailable. ');
    end;
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
  SilentHub, SubnetParam, PowerParam: String;
begin
  UpgradePage := CreateCustomPage(wpWelcome, 'Upgrade - keep current settings',
    'Your existing Computer Host Agent configuration');
  UpgradeDeviceHint := TNewStaticText.Create(UpgradePage);
  UpgradeDeviceHint.Parent := UpgradePage.Surface;
  UpgradeDeviceHint.Width := UpgradePage.SurfaceWidth;
  UpgradeDeviceHint.AutoSize := False;
  UpgradeDeviceHint.WordWrap := True;
  UpgradeDeviceHint.Height := ScaleY(42);
  UpgradeDeviceHint.Font.Style := [fsBold];
  UpgradeDeviceHint.Caption := 'If already connected to SmartThings, no new device is needed.';

  UpgradeSummary := TNewStaticText.Create(UpgradePage);
  UpgradeSummary.Parent := UpgradePage.Surface;
  UpgradeSummary.Top := UpgradeDeviceHint.Top + UpgradeDeviceHint.Height + ScaleY(8);
  UpgradeSummary.Width := UpgradePage.SurfaceWidth;
  UpgradeSummary.AutoSize := False;
  UpgradeSummary.WordWrap := True;
  UpgradeSummary.Height := ScaleY(75);
  ChangeSettingsCheck := TNewCheckBox.Create(UpgradePage);
  ChangeSettingsCheck.Parent := UpgradePage.Surface;
  ChangeSettingsCheck.Top := UpgradeSummary.Top + UpgradeSummary.Height + ScaleY(12);
  ChangeSettingsCheck.Width := UpgradePage.SurfaceWidth;
  ChangeSettingsCheck.Height := ScaleY(22);
  ChangeSettingsCheck.Caption := 'Change settings';
  ChangeSettingsCheck.Checked := False;

  HubPage := CreateCustomPage(UpgradePage.ID, 'SmartThings hub', 'Find the hub on your local network');
  LabelText := TNewStaticText.Create(HubPage);
  LabelText.Parent := HubPage.Surface;
  LabelText.Caption := 'SmartThings hub IP address:';
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
  HubSelect.OnChange := @HubChoiceChanged;

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
  HubStatus.Top := HubSelect.Top + HubSelect.Height + ScaleY(10);
  HubStatus.Width := HubPage.SurfaceWidth;
  HubStatus.AutoSize := False;
  HubStatus.Height := ScaleY(30);
  HubStatus.WordWrap := True;
  SetHubStatus('The installer will look for SmartThings hubs when this page opens.');

  // Same total height as the former three-line status, so nothing below moves.
  HubTip := TNewStaticText.Create(HubPage);
  HubTip.Parent := HubPage.Surface;
  HubTip.Top := HubStatus.Top + HubStatus.Height;
  HubTip.Width := HubPage.SurfaceWidth;
  HubTip.AutoSize := False;
  HubTip.Height := ScaleY(14);
  HubTip.WordWrap := False;
  HubTip.Caption := 'Tip: give the hub a fixed IP address in your router.';

  AdvancedButton := TNewButton.Create(HubPage);
  AdvancedButton.Parent := HubPage.Surface;
  AdvancedButton.Top := HubTip.Top + HubTip.Height + ScaleY(5);
  AdvancedButton.Width := ScaleX(160);
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
  LocalHelp.Caption := 'Use this option if your SmartThings hub cannot be detected automatically and you do not know its IP address. The rule remains Private-only.';

  // Always visible: Setup's loopback health check cannot prove the hub can
  // reach a host whose network profile is Public. Never broaden the firewall.
  NetworkProfileHint := TNewStaticText.Create(HubPage);
  NetworkProfileHint.Parent := HubPage.Surface;
  NetworkProfileHint.Top := LocalHelp.Top + LocalHelp.Height + ScaleY(8);
  NetworkProfileHint.Width := HubPage.SurfaceWidth;
  NetworkProfileHint.AutoSize := False;
  NetworkProfileHint.Height := ScaleY(48);
  NetworkProfileHint.WordWrap := True;
  NetworkProfileHint.Caption := 'Windows firewall: Private networks only. If this PC is on a Public network, your hub may not connect even when local health checks pass. Review the network profile in Windows Settings.';
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
  PowerCheck.Caption := 'Allow SmartThings to shut down, restart and put this PC to sleep';
  PowerCheck.Checked := False;

  // Caption depends on the inspected installation; set in InitializeWizard.
  PowerNote := TNewStaticText.Create(PowerPage);
  PowerNote.Parent := PowerPage.Surface;
  PowerNote.Width := PowerPage.SurfaceWidth;
  PowerNote.Top := PowerCheck.Top + PowerCheck.Height + ScaleY(12);
  PowerNote.Height := ScaleY(32);
  PowerNote.WordWrap := True;
  PowerNote.AutoSize := False;
  ConfirmPowerCheck := TNewCheckBox.Create(PowerPage);
  ConfirmPowerCheck.Parent := PowerPage.Surface;
  ConfirmPowerCheck.Top := PowerNote.Top + PowerNote.Height + ScaleY(5);
  ConfirmPowerCheck.Width := PowerPage.SurfaceWidth;
  ConfirmPowerCheck.Height := ScaleY(22);
  ConfirmPowerCheck.Caption := 'I confirm the power setting above';
  ConfirmPowerCheck.Visible := False;

  // Waking is configured outside Setup on Windows; say where, once.
  WolHint := TNewStaticText.Create(PowerPage);
  WolHint.Parent := PowerPage.Surface;
  WolHint.Width := PowerPage.SurfaceWidth;
  WolHint.Top := ConfirmPowerCheck.Top + ConfirmPowerCheck.Height + ScaleY(12);
  WolHint.Height := ScaleY(46);
  WolHint.WordWrap := True;
  WolHint.AutoSize := False;
  WolHint.Caption := 'To switch this PC on from SmartThings, enable Wake-on-LAN in the network adapter''s properties and in the BIOS/UEFI. Setup does not change these settings.';

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

  InspectPreviousConfiguration(PreviousScope, PreviousPower);
  PowerCheck.Checked := PreviousPower;
  if ExistingInstallation then
  begin
    Searched := (PreviousScope <> 'unknown'); // Search only if no valid scope was retained.
    if IsValidIPv4(PreviousScope) then
    begin
      HubSelect.Text := PreviousScope;
      SetHubStatus('Keeping previous hub address. Search again to change it.');
    end
    else if PreviousScope = 'LocalSubnet' then
    begin
      LocalSubnetCheck.Checked := True;
      SetHubStatus('Keeping previous Private local-network scope. Change it if needed.');
      SetAdvancedVisible(True);
    end
    else
    begin
      SetHubStatus('Previous firewall scope is missing or ambiguous. Explicitly select a hub or local-network scope.');
      SetAdvancedVisible(True);
    end;
  end;
  SilentHub := ExpandConstant('{param:HUBIP|}');
  SubnetParam := ExpandConstant('{param:LOCALSUBNET|}');
  PowerParam := ExpandConstant('{param:ENABLEPOWER|}');
  InvalidArguments := ((SilentHub <> '') and not IsValidIPv4(SilentHub)) or
    ((SubnetParam <> '') and (SubnetParam <> '0') and (SubnetParam <> '1')) or
    ((PowerParam <> '') and (PowerParam <> '0') and (PowerParam <> '1')) or
    ((SilentHub <> '') and (SubnetParam = '1'));
  if SilentHub <> '' then
  begin
    LocalSubnetCheck.Checked := False;
    HubSelect.Text := SilentHub;
    SetHubStatus('Using the supplied hub IP address. You can change it if necessary.');
  end
  else if SubnetParam = '1' then
  begin
    LocalSubnetCheck.Checked := True;
    SetAdvancedVisible(True);
  end
  else if SubnetParam = '0' then
    LocalSubnetCheck.Checked := False;
  ChangeSubnetScope(nil);
  if PowerParam <> '' then PowerCheck.Checked := PowerParam = '1';
  ExplicitScope := IsValidIPv4(SilentHub) or (SubnetParam = '1');
  ExplicitPower := (PowerParam = '0') or (PowerParam = '1');
  ShowUpgradeSummary := ExistingInstallation and not InspectionFailed and
    (PreviousScope <> 'unknown') and (SilentHub = '') and (SubnetParam = '') and (PowerParam = '');
  if PreviousScope = 'LocalSubnet' then
    UpgradeSummary.Caption := 'Network access: Private local network (LocalSubnet)'
  else
    UpgradeSummary.Caption := 'SmartThings hub: ' + PreviousScope;
  if PreviousPower then
    UpgradeSummary.Caption := UpgradeSummary.Caption + #13#10 + 'Power control: enabled'
  else
    UpgradeSummary.Caption := UpgradeSummary.Caption + #13#10 + 'Power control: disabled';
  UpgradeSummary.Caption := UpgradeSummary.Caption + #13#10#13#10 +
    'Your existing identity and settings will be kept.';
  ConfirmPowerCheck.Visible := InspectionFailed and not ExplicitPower;
  if ExistingInstallation then
    PowerNote.Caption := 'Upgrades keep your existing power-control setting. The key is shown after installation.'
  else
    PowerNote.Caption := 'If you allow this, the power control key is shown after installation.';
  if InspectionFailed then
    SetHubStatus('Could not read previous settings. Select a network scope and confirm your power preference.');
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if (CurPageID = HubPage.ID) and (not Searched) and (not WizardSilent) and
     (HubSelect.Text = '') and not LocalSubnetCheck.Checked then
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
      WizardForm.FinishedLabel.Caption :=
        'The installation could not be verified or completed. Check the setup log and recovery guidance before retrying.';
    end
    else
    begin
      if InstallWasUpgrade and InstallCommitted then
      begin
        WizardForm.FinishedHeadingLabel.Caption := 'Computer Host LAN upgrade complete';
        WizardForm.FinishedLabel.Caption :=
          'The agent passed the local health, version and identity checks. Your existing SmartThings device does not need to be added again if already connected.';
        if RetainedPowerKey then
          WizardForm.FinishedLabel.Caption := WizardForm.FinishedLabel.Caption +
            ' Your existing power key is unchanged; no new key needs to be entered.';
        WizardForm.FinishedLabel.Caption := WizardForm.FinishedLabel.Caption +
          ' If you changed your settings, check that SmartThings and the new network scope agree. The setup guide remains available in the Start Menu.';
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
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := ((PageID = UpgradePage.ID) and not ShowUpgradeSummary) or
    (((PageID = HubPage.ID) or (PageID = PowerPage.ID)) and
      ShowUpgradeSummary and not ChangeSettingsCheck.Checked) or
    ((PageID = ConnectPage.ID) and InstallWasUpgrade and InstallCommitted) or
    ((PageID = KeyPage.ID) and (not PowerCheck.Checked or InstallFailed or WizardSilent or
      (InstallWasUpgrade and InstallCommitted and RetainedPowerKey)));
end;

function SelectedHubIP: String;
begin
  Result := HubIPv4FromSelection(HubSelect.Text);
end;

function ValidConfiguration: Boolean;
begin
  Result := LocalSubnetCheck.Checked or IsValidIPv4(SelectedHubIP());
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  // In silent mode Inno still calls this event. Returning False would
  // strand the hidden wizard on a page with no user to correct the input.
  // PrepareToInstall validates every silent choice and aborts with an error.
  if WizardSilent then Exit;
  if (CurPageID = HubPage.ID) and not ValidConfiguration then
  begin
    MsgBox('Select or enter your SmartThings hub IP address, or use Advanced options to allow local-network access.',
      mbError, MB_OK);
    Result := False;
    Exit;
  end;
  if CurPageID = UpgradePage.ID then
  begin
    if not ChangeSettingsCheck.Checked then
    begin
      LocalSubnetCheck.Checked := PreviousScope = 'LocalSubnet';
      if LocalSubnetCheck.Checked then HubSelect.Text := ''
      else HubSelect.Text := PreviousScope;
      SetAdvancedVisible(LocalSubnetCheck.Checked);
      ChangeSubnetScope(nil);
      PowerCheck.Checked := PreviousPower;
    end;
  end;
  if CurPageID = HubPage.ID then ScopeConfirmed := True;
  if CurPageID = PowerPage.ID then
  begin
    if InspectionFailed and not ExplicitPower and not ConfirmPowerCheck.Checked then
    begin
      MsgBox('Confirm your power preference before continuing.', mbError, MB_OK);
      Result := False;
      Exit;
    end;
    PowerConfirmed := True;
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
    mbError, MB_OK)
  else SnapshotRecovered := True;
end;

// Require a healthy new agent before removing the last known-good snapshot.
function CheckAgentBeforeCommit: Boolean;
var
  ExitCode: Integer;
  Params: String;
begin
  ExtractTemporaryFile('Check-WindowsAgentHealth.ps1');
  Params := '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' +
    ExpandConstant('{tmp}\Check-WindowsAgentHealth.ps1') + '" -ExpectedVersion "{#WindowsAgentVersion}"';
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
  if InvalidArguments then
  begin
    Result := 'Conflicting or invalid arguments. Use /HUBIP=<IPv4> or /LOCALSUBNET=1, and /ENABLEPOWER=0 or 1. No installation changes made.';
    Exit;
  end;
  if InspectionFailed and
    ((WizardSilent and (not ExplicitScope or not ExplicitPower)) or
     (not WizardSilent and ((not ExplicitScope and not ScopeConfirmed) or
       (not ExplicitPower and not PowerConfirmed)))) then
  begin
    Result := 'Unable to read previous settings. Explicitly select network and power settings, or pass /HUBIP=<IPv4> or /LOCALSUBNET=1 together with /ENABLEPOWER=0 or 1. No installation changes made.';
    Exit;
  end;
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
  if SnapshotRecovered then
  begin
    Result := 'The previous installation was restored. Restart Setup to read the restored settings before upgrading.';
    Exit;
  end;
  // Validate the actual chosen settings and existing state before stopping
  // the service. This is separate from the optional initial preference read.
  if not FileExists(ExpandConstant('{tmp}\Install-WindowsAgent.ps1')) then
    ExtractTemporaryFile('Install-WindowsAgent.ps1');
  DiagnosticFile := ExpandConstant('{tmp}\computerhost-validation-error.txt');
  DeleteFile(DiagnosticFile);
  Params := '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' +
    ExpandConstant('{tmp}\Install-WindowsAgent.ps1') + '" -ValidateOnly -DiagnosticPath "' + DiagnosticFile + '"';
  if LocalSubnetCheck.Checked then Params := Params + ' -LocalSubnet'
  else Params := Params + ' -HubIPv4 ' + SelectedHubIP;
  if PowerCheck.Checked then Params := Params + ' -EnablePower'
  else Params := Params + ' -DisablePower';
  if not ExecWithNativeSysDir(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
    Params, '', SW_HIDE, ewWaitUntilTerminated, ExitCode) or (ExitCode <> 0) then
  begin
    Result := 'Existing installation or selected settings failed safety validation. No application files were replaced.';
    if LoadStringFromFile(DiagnosticFile, Details) then
    begin
      Log(String(Details));
      Result := Result + ' ' + String(Details);
    end;
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
  Params, DiagnosticFile, FailureMessage, ResultFile, Reply: String;
  ExitCode: Integer;
  Details, Raw: AnsiString;
begin
  if CurStep <> ssPostInstall then Exit;
  ResultFile := ExpandConstant('{tmp}\computerhost-install-result.txt');
  DeleteFile(ResultFile);
  DiagnosticFile := ExpandConstant('{tmp}\computerhost-service-installation.txt');
  DeleteFile(DiagnosticFile);
  Params := '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' +
    ExpandConstant('{app}\Installer\Install-WindowsAgent.ps1') +
    '" -PublishedDirectory "' + ExpandConstant('{app}') +
    '" -UseExistingFiles -DiagnosticPath "' + DiagnosticFile + '" -InstallResultPath "' + ResultFile + '"';
  if LocalSubnetCheck.Checked then Params := Params + ' -LocalSubnet'
  else Params := Params + ' -HubIPv4 ' + SelectedHubIP;
  if PowerCheck.Checked then Params := Params + ' -EnablePower'
  else Params := Params + ' -DisablePower';
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
      // State may be recoverable. Say what failed before attempting rollback.
      if not WizardSilent then
        MsgBox('The agent did not pass the health, version or identity check. ' +
          'Setup will try to restore a previous installation, if one exists. If recovery fails, ' +
          'keep the rollback files and consult the installation guide.', mbError, MB_OK);
      FinishUpgrade('Restore');
    end
    else if FinishUpgrade('Commit') then
    begin
      InstallCommitted := True;
      AgentHealthy := True;
      if LoadStringFromFile(ResultFile, Raw) then
      begin
        Reply := Trim(String(Raw));
        InstallWasUpgrade := (Reply = 'upgrade|key-retained') or (Reply = 'upgrade|key-not-retained');
        RetainedPowerKey := Reply = 'upgrade|key-retained';
      end;
    end
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
