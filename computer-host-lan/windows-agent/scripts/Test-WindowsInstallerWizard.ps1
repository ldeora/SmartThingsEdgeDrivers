# Smoke-test actual HWND wizard controls on a Windows CI runner.
# By default, only inspects Welcome and the hub field. -FullInstall
# exercises a real graphical upgrade and validates the post-install wizard.
# Never prints the authentication key or stores it in logs.
[CmdletBinding()]
param([Parameter(Mandatory)][string]$SetupExecutable,
      [switch]$FullInstall,
      [switch]$MonitoringOnly,
      [switch]$SubnetFallback)
$ErrorActionPreference = 'Stop'

Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
public static class ComputerHostWizardProbe {
    public class Item {
        public IntPtr Handle;
        public string Text;
        public string Class;
        public bool Visible;
        public int Left, Top, Width, Height;
        public override string ToString() {
            return Class + " \"" + Text + "\" visible=" + Visible + " bounds=" +
              Left + "," + Top + "," + Width + "," + Height;
        }
    }
    private delegate bool Enumerate(IntPtr hWnd, IntPtr data);
    [StructLayout(LayoutKind.Sequential)]
    private struct RECT { public int Left, Top, Right, Bottom; }
    [DllImport("user32.dll")] private static extern bool EnumWindows(Enumerate e, IntPtr data);
    [DllImport("user32.dll")] private static extern bool EnumChildWindows(IntPtr parent, Enumerate e, IntPtr data);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] private static extern int GetWindowText(IntPtr h, StringBuilder text, int max);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] private static extern int GetClassName(IntPtr h, StringBuilder text, int max);
    [DllImport("user32.dll")] private static extern bool GetWindowRect(IntPtr h, out RECT rect);
    [DllImport("user32.dll")] private static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern bool SetWindowText(IntPtr h, string value);
    [DllImport("user32.dll")] private static extern IntPtr SendMessage(IntPtr h, uint m, IntPtr w, IntPtr l);
    [DllImport("user32.dll", SetLastError=true)] private static extern bool OpenClipboard(IntPtr h);
    [DllImport("user32.dll")] private static extern bool CloseClipboard();
    [DllImport("user32.dll")] private static extern IntPtr GetClipboardData(uint format);
    [DllImport("kernel32.dll")] private static extern IntPtr GlobalLock(IntPtr h);
    [DllImport("kernel32.dll")] private static extern bool GlobalUnlock(IntPtr h);
    [DllImport("user32.dll")] private static extern uint GetWindowThreadProcessId(IntPtr h, out uint processId);
    public static Item Read(IntPtr h) {
        var t = new StringBuilder(1024);
        var c = new StringBuilder(256);
        GetWindowText(h, t, t.Capacity);
        GetClassName(h, c, c.Capacity);
        // Never collect or print the contents of edit controls (including
        // the private key field) when enumerating the wizard HWND tree.
        if (c.ToString().IndexOf("Edit", StringComparison.OrdinalIgnoreCase) >= 0 ||
            c.ToString().IndexOf("ComboBox", StringComparison.OrdinalIgnoreCase) >= 0)
            t.Clear();
        RECT r;
        bool hasRect = GetWindowRect(h, out r);
        return new Item { Handle = h, Text = t.ToString(), Class = c.ToString(),
            Visible = IsWindowVisible(h), Left = hasRect ? r.Left : 0,
            Top = hasRect ? r.Top : 0, Width = hasRect ? r.Right - r.Left : 0,
            Height = hasRect ? r.Bottom - r.Top : 0 };
    }
    public static Item[] Windows() {
        var r = new List<Item>();
        EnumWindows((h,d) => { r.Add(Read(h)); return true; }, IntPtr.Zero);
        return r.ToArray();
    }
    public static Item[] Children(IntPtr parent) {
        var r = new List<Item>();
        EnumChildWindows(parent, (h,d) => { r.Add(Read(h)); return true; }, IntPtr.Zero);
        return r.ToArray();
    }
    public static void Click(IntPtr hwnd) { SendMessage(hwnd, 0x00F5, IntPtr.Zero, IntPtr.Zero); }
    public static bool IsChecked(IntPtr hwnd) { return SendMessage(hwnd, 0x00F0, IntPtr.Zero, IntPtr.Zero).ToInt64() == 1; }
    public static string TextOf(IntPtr hwnd) {
        var text = new StringBuilder(512);
        GetWindowText(hwnd, text, text.Capacity);
        return text.ToString();
    }
    public static int PasswordMask(IntPtr hwnd) {
        return (int)SendMessage(hwnd, 0x00D2, IntPtr.Zero, IntPtr.Zero).ToInt64();
    }
    public static string ClipboardText() {
        if (!OpenClipboard(IntPtr.Zero)) return null;
        try {
            IntPtr h = GetClipboardData(13); // CF_UNICODETEXT
            if (h == IntPtr.Zero) return null;
            IntPtr ptr = GlobalLock(h);
            if (ptr == IntPtr.Zero) return null;
            try { return Marshal.PtrToStringUni(ptr); }
            finally { GlobalUnlock(h); }
        }
        finally { CloseClipboard(); }
    }
    public static int ProcessId(IntPtr hwnd) {
        uint id; GetWindowThreadProcessId(hwnd, out id); return (int)id;
    }
}
'@ -ErrorAction Stop

$setup = (Resolve-Path -LiteralPath $SetupExecutable).Path
Write-Host ("Wizard GUI test: " + $(if ($FullInstall) { 'interactive upgrade' } else { 'navigation-only (no install)' }))
function VisibleControls([IntPtr]$handle) {
    return @([ComputerHostWizardProbe]::Children($handle) |
        Where-Object { $_.Visible })
}
function FindVisibleButton([IntPtr]$handle, [string]$pattern) {
    return (VisibleControls $handle | Where-Object {
        $_.Class -match 'Button' -and $_.Text -match $pattern
    } | Select-Object -First 1)
}
function ClickWizardButton([IntPtr]$handle, [string]$pattern) {
    $button = FindVisibleButton $handle $pattern
    if (-not $button) { throw "Wizard button not found: $pattern" }
    [ComputerHostWizardProbe]::Click($button.Handle)
}
function WaitForWizardText([IntPtr]$handle, [string]$pattern, [string]$stage, [int]$ticks = 130) {
    for ($attempt = 0; $attempt -lt $ticks; $attempt++) {
        $matches = @(VisibleControls $handle | Where-Object { $_.Text -match $pattern })
        if ($matches.Count -gt 0) { Write-Host "PASS $stage"; return }
        Start-Sleep -Milliseconds 350
    }
    $c = VisibleControls $handle | Where-Object { $_.Text -and $_.Class -notmatch 'Edit' }
    Write-Host 'Visible labels/buttons at timeout:'
    $c | ForEach-Object { Write-Host "$_" }
    throw "Wizard did not show $stage"
}
function CaptureWizardPage([ComputerHostWizardProbe+Item]$window, [string]$name) {
    # Capture ONLY non-secret pages, never the authentication key UI.
    try {
        Add-Type -AssemblyName System.Drawing
        $folder = Join-Path $env:RUNNER_TEMP 'computer-host-wizard-screens'
        New-Item -ItemType Directory -Path $folder -Force | Out-Null
        $bitmap = [System.Drawing.Bitmap]::new($window.Width, $window.Height)
        $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
        try {
            $graphics.CopyFromScreen($window.Left, $window.Top, 0, 0,
                [System.Drawing.Size]::new($window.Width, $window.Height))
            $bitmap.Save((Join-Path $folder ($name + '.png')),
                [System.Drawing.Imaging.ImageFormat]::Png)
            Write-Host "Captured safe UI screenshot: $name"
        } finally {
            $graphics.Dispose()
            $bitmap.Dispose()
        }
    } catch {
        Write-Warning "Screen capture unavailable: $($_.Exception.GetType().Name)"
    }
}
function WaitForClipboard([string]$expected, [string]$stage) {
    for ($attempt = 0; $attempt -lt 16; $attempt++) {
        $actual = [ComputerHostWizardProbe]::ClipboardText()
        if ($actual -ceq $expected) { Write-Host "PASS $stage"; return }
        Start-Sleep -Milliseconds 150
    }
    throw "Clipboard copy did not match expected $stage (secret withheld)"
}
$proc = $null
$window = $null
try {
    $args = if ($FullInstall) {
        if ($MonitoringOnly) { '/ENABLEPOWER=0' } else { '/HUBIP=192.0.2.20 /ENABLEPOWER=1' }
    } else { '' }
    $modeSuffix = if ($MonitoringOnly) { '-monitoring-only' } else { '-power-enabled' }
    $proc = Start-Process -FilePath $setup -ArgumentList $args -PassThru
    for ($attempt = 0; $attempt -lt 70; $attempt++) {
        $window = [ComputerHostWizardProbe]::Windows() |
            Where-Object { $_.Visible -and $_.Text -match 'Computer Host LAN.*Setup|Setup.*Computer Host LAN' } |
            Select-Object -First 1
        if ($window) { break }
        Start-Sleep -Milliseconds 400
    }
    if (-not $window) { throw 'No visible Setup window found; GUI desktop may be unavailable on this runner.' }
    Write-Host "Wizard: $window"

    $children = @([ComputerHostWizardProbe]::Children($window.Handle))
    $welcome = @($children | Where-Object {
        $_.Visible -and $_.Text -match 'Welcome to.*Computer Host|Welcome to the.*Setup Wizard'
    })
    if ($welcome.Count -eq 0) {
        Write-Host 'Initial visible controls:'
        $children | Where-Object { $_.Visible -and $_.Text } | ForEach-Object { Write-Host "$_" }
        throw 'Welcome heading not visible; DisableWelcomePage=no should be effective.'
    }
    Write-Host 'PASS Welcome screen heading is visible'
    CaptureWizardPage $window ('01-welcome' + $modeSuffix)

    $next = $children | Where-Object {
        $_.Visible -and $_.Class -match 'Button' -and $_.Text -match 'Next'
    } | Select-Object -First 1
    if (-not $next) { throw 'Welcome Next button is not visible' }
    [ComputerHostWizardProbe]::Click($next.Handle)

    $onHub = $false
    for ($attempt = 0; $attempt -lt 70; $attempt++) {
        $children = @([ComputerHostWizardProbe]::Children($window.Handle))
        if (@($children | Where-Object {
            $_.Visible -and $_.Text -match 'SmartThings hub IPv4 \(DHCP reservation recommended'
        }).Count -gt 0) {
            $onHub = $true
            break
        }
        Start-Sleep -Milliseconds 350
    }
    if (-not $onHub) {
        $children | Where-Object { $_.Visible -and $_.Text } | ForEach-Object { Write-Host "$_" }
        throw 'SmartThings hub page never became visible after Welcome'
    }
    Write-Host 'PASS SmartThings hub configuration page visible'

    $input = $children | Where-Object {
        $_.Visible -and $_.Class -match 'ComboBox' -and
        $_.Width -ge 100 -and $_.Height -ge 15
    } | Select-Object -First 1
    if (-not $input) {
        $children | Where-Object { $_.Class -match 'ComboBox|Edit' } |
            ForEach-Object { Write-Host "Hub input candidate: $_" }
        throw 'Hub IPv4 input is absent, hidden, or has invalid size'
    }
    if ($input.Left -lt $window.Left -or $input.Top -lt $window.Top -or
        $input.Left + $input.Width -gt $window.Left + $window.Width -or
        $input.Top + $input.Height -gt $window.Top + $window.Height) {
        throw "Hub IPv4 input falls outside the Setup window: $input"
    }
    Write-Host "PASS visible, on-screen, editable hub address selector: $input"
    if (-not [ComputerHostWizardProbe]::SetWindowText($input.Handle, '192.0.2.20')) {
        throw 'Hub IPv4 selector refused manual text entry'
    }
    if ([ComputerHostWizardProbe]::TextOf($input.Handle) -ne '192.0.2.20') {
        throw 'Hub IPv4 selector did not retain manually entered address'
    }
    Write-Host 'PASS manual hub-IP entry accepts and displays IPv4 text'
    # A discovered hub is shown as "IPv4 (friendly name)" in the editable
    # selector. If mDNS disappears during Search again, the previously valid
    # address must remain usable instead of silently disappearing.
    if (-not [ComputerHostWizardProbe]::SetWindowText($input.Handle,
        '192.0.2.20 (Previously discovered hub)')) {
        throw 'Could not set a discovered-hub label for the retry regression test'
    }
    ClickWizardButton $window.Handle '^Search again
    if (-not $advanced) { throw 'Advanced options button missing' }
    $before = @(VisibleControls $window.Handle | Where-Object {
        $_.Text -match '^Allow connections from devices on my local network$'
    }).Count -gt 0
    ClickWizardButton $window.Handle 'Advanced options'
    Start-Sleep -Milliseconds 150
    $after = @(VisibleControls $window.Handle | Where-Object {
        $_.Text -match '^Allow connections from devices on my local network$'
    }).Count -gt 0
    if ($before -eq $after) { throw 'Advanced options did not toggle the local-network fallback' }
    ClickWizardButton $window.Handle 'Advanced options'
    Write-Host 'PASS Advanced options shows/hides the local-network firewall fallback'
    if ($SubnetFallback) {
        if (-not [ComputerHostWizardProbe]::SetWindowText($input.Handle, '')) {
            throw 'Could not clear manual hub address to test LocalSubnet fallback'
        }
        # Discovery failure expands Advanced options automatically, whereas
        # successful discovery initially collapses it. Do not toggle blindly.
        $subnet = VisibleControls $window.Handle | Where-Object {
            $_.Text -match '^Allow connections from devices on my local network$'
        } | Select-Object -First 1
        if (-not $subnet) {
            ClickWizardButton $window.Handle 'Advanced options'
            $subnet = VisibleControls $window.Handle | Where-Object {
                $_.Text -match '^Allow connections from devices on my local network$'
            } | Select-Object -First 1
        }
        if (-not $subnet) { throw 'Local-network fallback checkbox is not visible' }
        [ComputerHostWizardProbe]::Click($subnet.Handle)
        if (-not [ComputerHostWizardProbe]::IsChecked($subnet.Handle)) {
            throw 'Local-network firewall checkbox did not become checked'
        }
        Write-Host 'PASS user explicitly enabled local-network firewall fallback without knowing a hub IP'
    }
    CaptureWizardPage $window ('02-hub' + $modeSuffix)
    $rescan = $children | Where-Object { $_.Visible -and $_.Text -match 'Search again' } | Select-Object -First 1
    if (-not $rescan) { throw 'Search again button not visible' }
    Write-Host 'PASS Search again button visible'
    Write-Host 'PASS graphical Welcome and hub selector smoke test'
    if ($FullInstall) {
        ClickWizardButton $window.Handle 'Next'
        WaitForWizardText $window.Handle 'Enable authenticated shutdown, reboot and suspend' 'power-management page'
        $cb = VisibleControls $window.Handle |
            Where-Object { $_.Class -match 'CheckBox' -and $_.Text -match 'Enable authenticated shutdown' } |
            Select-Object -First 1
        if (-not $cb) { throw 'Power-management checkbox is not visible' }
        Write-Host 'PASS power-management checkbox visible'
        $powerEnabled = [ComputerHostWizardProbe]::IsChecked($cb.Handle)
        if ($MonitoringOnly -and $powerEnabled) { throw 'Monitoring-only interactive install unexpectedly prechecked power' }
        if (-not $MonitoringOnly -and -not $powerEnabled) { throw 'Power-enabled interactive install did not precheck power' }
        CaptureWizardPage $window ('03-power' + $modeSuffix)

        ClickWizardButton $window.Handle 'Next'
        WaitForWizardText $window.Handle 'Ready to Install' 'confirmation page'
        ClickWizardButton $window.Handle 'Install'
        WaitForWizardText $window.Handle 'Open driver channel' 'post-install SmartThings connection page' 240
        WaitForWizardText $window.Handle 'Scan nearby' 'SmartThings device discovery guidance'
        $status = @(VisibleControls $window.Handle | Where-Object {
            $_.Text -match 'Computer Host Agent is running and responding'
        })
        if ($status.Count -eq 0) { throw 'Connect page does not confirm the agent is healthy' }
        CaptureWizardPage $window ('04-connect' + $modeSuffix)

        ClickWizardButton $window.Handle 'Copy invitation link'
        WaitForClipboard 'https://bestow-regional.api.smartthings.com/invite/1J2Qy7ZkxL20' 'channel link copying'
        ClickWizardButton $window.Handle 'Next'
        if ($MonitoringOnly) {
            WaitForWizardText $window.Handle 'Computer Host LAN is installed' 'monitoring-only skips private key page'
            if (@(VisibleControls $window.Handle | Where-Object {
                $_.Text -match 'Copy authentication key|Your private authentication key'
            }).Count -gt 0) { throw 'Monitoring-only wizard exposed a private-key page' }
            Write-Host 'PASS monitoring-only wizard skips authentication key page'
        } else {
            WaitForWizardText $window.Handle 'Your private authentication key' 'post-install authentication page'
            $keyEdit = VisibleControls $window.Handle | Where-Object {
                $_.Class -match 'Edit' -and $_.Width -ge 100
            } | Select-Object -First 1
            if (-not $keyEdit) { throw 'Authentication key edit field missing' }
            $initialMask = [ComputerHostWizardProbe]::PasswordMask($keyEdit.Handle)
            Write-Host "Authentication key field mask character code: $initialMask"
            if ($initialMask -eq 0) {
                throw 'Authentication key is not masked by default'
            }
            Write-Host 'PASS private key is masked by default'
            ClickWizardButton $window.Handle 'Show key'
            # Inno's TNewEdit may recreate its native HWND when PasswordChar
            # changes; always inspect the CURRENT visible edit rather than
            # retaining a handle from before the property setter ran.
            $keyEditAfterShow = VisibleControls $window.Handle | Where-Object {
                $_.Class -match 'Edit' -and $_.Width -ge 100
            } | Select-Object -First 1
            if (-not $keyEditAfterShow) { throw 'Key edit missing after Show key' }
            $shownMask = [ComputerHostWizardProbe]::PasswordMask($keyEditAfterShow.Handle)
            Write-Host "Mask code after Show: $shownMask"
            if ($shownMask -ne 0) {
                throw 'Show key did not reveal the field'
            }
            ClickWizardButton $window.Handle 'Hide key'
            $keyEditAfterHide = VisibleControls $window.Handle | Where-Object {
                $_.Class -match 'Edit' -and $_.Width -ge 100
            } | Select-Object -First 1
            if (-not $keyEditAfterHide) { throw 'Key edit missing after Hide key' }
            $restoredMask = [ComputerHostWizardProbe]::PasswordMask($keyEditAfterHide.Handle)
            Write-Host "Mask code after Hide: $restoredMask"
            if ($restoredMask -eq 0) {
                throw 'Hide key did not restore password masking'
            }
            Write-Host 'PASS Show/Hide authentication key toggle'
            $keyPath = Join-Path $env:ProgramData 'ComputerHostAgent/control-token'
            if (-not (Test-Path -LiteralPath $keyPath)) { throw 'Power key was not generated' }
            $key = (Get-Content -LiteralPath $keyPath -Raw).Trim()
            if ($key -cnotmatch '^[a-f0-9]{64}$') { throw 'Invalid key format (value withheld)' }
            ClickWizardButton $window.Handle 'Copy authentication key'
            WaitForClipboard $key 'authentication key copying'
            $key = $null
            ClickWizardButton $window.Handle 'Next'
            WaitForWizardText $window.Handle 'Computer Host LAN is installed' 'completed installer page'
        }
        ClickWizardButton $window.Handle 'Finish'
        if ($MonitoringOnly) {
            $info = Invoke-RestMethod http://127.0.0.1:8765/v2/info
            if ($info.power_actions.Count -ne 0) { throw 'Monitoring-only GUI install left privileged commands enabled' }
            if ($SubnetFallback) {
                $addresses = @((Get-NetFirewallRule -Name 'ComputerHostAgent-TCP8765' |
                    Get-NetFirewallAddressFilter).RemoteAddress)
                if ($addresses -notcontains 'LocalSubnet') {
                    throw 'Graphical LocalSubnet fallback did not configure firewall'
                }
            }
            Write-Host 'PASS graphical monitoring-only setup, no key page and LocalSubnet firewall'
        }
        Write-Host 'PASS complete native Windows GUI installation and onboarding workflow'
    }
} finally {
    if ($window) {
        $processId = [ComputerHostWizardProbe]::ProcessId($window.Handle)
        $candidate = Get-Process -Id $processId -ErrorAction SilentlyContinue
        if ($candidate -and $candidate.Path -and
            ($candidate.Path -ieq $setup -or $candidate.ProcessName -like '*setup*')) {
            Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
        }
    }
    if ($proc) {
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
        $proc.Dispose()
    }
}

    $rescanStatus = @(VisibleControls $window.Handle | Where-Object {
        $_.Text -match 'No hub detected|Discovery unavailable'
    }).Count -gt 0
    $rescanInput = VisibleControls $window.Handle | Where-Object {
        $_.Class -match 'ComboBox' -and $_.Width -ge 100 -and $_.Height -ge 15
    } | Select-Object -First 1
    if (-not $rescanInput) { throw 'Hub selector disappeared after retry' }
    if ($rescanStatus) {
        if ([ComputerHostWizardProbe]::TextOf($rescanInput.Handle) -ne '192.0.2.20') {
            throw 'Failed hub rediscovery lost previously selected valid IPv4 address'
        }
        Write-Host 'PASS failed rediscovery preserves discovered hub IPv4 address'
    } else {
        Write-Host 'INFO no-discovery regression assertion skipped: hub(s) found on this runner'
    }
    $advanced = FindVisibleButton $window.Handle 'Advanced options'
    if (-not $advanced) { throw 'Advanced options button missing' }
    $before = @(VisibleControls $window.Handle | Where-Object {
        $_.Text -match '^Allow connections from devices on my local network$'
    }).Count -gt 0
    ClickWizardButton $window.Handle 'Advanced options'
    Start-Sleep -Milliseconds 150
    $after = @(VisibleControls $window.Handle | Where-Object {
        $_.Text -match '^Allow connections from devices on my local network$'
    }).Count -gt 0
    if ($before -eq $after) { throw 'Advanced options did not toggle the local-network fallback' }
    ClickWizardButton $window.Handle 'Advanced options'
    Write-Host 'PASS Advanced options shows/hides the local-network firewall fallback'
    if ($SubnetFallback) {
        if (-not [ComputerHostWizardProbe]::SetWindowText($input.Handle, '')) {
            throw 'Could not clear manual hub address to test LocalSubnet fallback'
        }
        # Discovery failure expands Advanced options automatically, whereas
        # successful discovery initially collapses it. Do not toggle blindly.
        $subnet = VisibleControls $window.Handle | Where-Object {
            $_.Text -match '^Allow connections from devices on my local network$'
        } | Select-Object -First 1
        if (-not $subnet) {
            ClickWizardButton $window.Handle 'Advanced options'
            $subnet = VisibleControls $window.Handle | Where-Object {
                $_.Text -match '^Allow connections from devices on my local network$'
            } | Select-Object -First 1
        }
        if (-not $subnet) { throw 'Local-network fallback checkbox is not visible' }
        [ComputerHostWizardProbe]::Click($subnet.Handle)
        if (-not [ComputerHostWizardProbe]::IsChecked($subnet.Handle)) {
            throw 'Local-network firewall checkbox did not become checked'
        }
        Write-Host 'PASS user explicitly enabled local-network firewall fallback without knowing a hub IP'
    }
    CaptureWizardPage $window ('02-hub' + $modeSuffix)
    $rescan = $children | Where-Object { $_.Visible -and $_.Text -match 'Search again' } | Select-Object -First 1
    if (-not $rescan) { throw 'Search again button not visible' }
    Write-Host 'PASS Search again button visible'
    Write-Host 'PASS graphical Welcome and hub selector smoke test'
    if ($FullInstall) {
        ClickWizardButton $window.Handle 'Next'
        WaitForWizardText $window.Handle 'Enable authenticated shutdown, reboot and suspend' 'power-management page'
        $cb = VisibleControls $window.Handle |
            Where-Object { $_.Class -match 'CheckBox' -and $_.Text -match 'Enable authenticated shutdown' } |
            Select-Object -First 1
        if (-not $cb) { throw 'Power-management checkbox is not visible' }
        Write-Host 'PASS power-management checkbox visible'
        $powerEnabled = [ComputerHostWizardProbe]::IsChecked($cb.Handle)
        if ($MonitoringOnly -and $powerEnabled) { throw 'Monitoring-only interactive install unexpectedly prechecked power' }
        if (-not $MonitoringOnly -and -not $powerEnabled) { throw 'Power-enabled interactive install did not precheck power' }
        CaptureWizardPage $window ('03-power' + $modeSuffix)

        ClickWizardButton $window.Handle 'Next'
        WaitForWizardText $window.Handle 'Ready to Install' 'confirmation page'
        ClickWizardButton $window.Handle 'Install'
        WaitForWizardText $window.Handle 'Open driver channel' 'post-install SmartThings connection page' 240
        WaitForWizardText $window.Handle 'Scan nearby' 'SmartThings device discovery guidance'
        $status = @(VisibleControls $window.Handle | Where-Object {
            $_.Text -match 'Computer Host Agent is running and responding'
        })
        if ($status.Count -eq 0) { throw 'Connect page does not confirm the agent is healthy' }
        CaptureWizardPage $window ('04-connect' + $modeSuffix)

        ClickWizardButton $window.Handle 'Copy invitation link'
        WaitForClipboard 'https://bestow-regional.api.smartthings.com/invite/1J2Qy7ZkxL20' 'channel link copying'
        ClickWizardButton $window.Handle 'Next'
        if ($MonitoringOnly) {
            WaitForWizardText $window.Handle 'Computer Host LAN is installed' 'monitoring-only skips private key page'
            if (@(VisibleControls $window.Handle | Where-Object {
                $_.Text -match 'Copy authentication key|Your private authentication key'
            }).Count -gt 0) { throw 'Monitoring-only wizard exposed a private-key page' }
            Write-Host 'PASS monitoring-only wizard skips authentication key page'
        } else {
            WaitForWizardText $window.Handle 'Your private authentication key' 'post-install authentication page'
            $keyEdit = VisibleControls $window.Handle | Where-Object {
                $_.Class -match 'Edit' -and $_.Width -ge 100
            } | Select-Object -First 1
            if (-not $keyEdit) { throw 'Authentication key edit field missing' }
            $initialMask = [ComputerHostWizardProbe]::PasswordMask($keyEdit.Handle)
            Write-Host "Authentication key field mask character code: $initialMask"
            if ($initialMask -eq 0) {
                throw 'Authentication key is not masked by default'
            }
            Write-Host 'PASS private key is masked by default'
            ClickWizardButton $window.Handle 'Show key'
            # Inno's TNewEdit may recreate its native HWND when PasswordChar
            # changes; always inspect the CURRENT visible edit rather than
            # retaining a handle from before the property setter ran.
            $keyEditAfterShow = VisibleControls $window.Handle | Where-Object {
                $_.Class -match 'Edit' -and $_.Width -ge 100
            } | Select-Object -First 1
            if (-not $keyEditAfterShow) { throw 'Key edit missing after Show key' }
            $shownMask = [ComputerHostWizardProbe]::PasswordMask($keyEditAfterShow.Handle)
            Write-Host "Mask code after Show: $shownMask"
            if ($shownMask -ne 0) {
                throw 'Show key did not reveal the field'
            }
            ClickWizardButton $window.Handle 'Hide key'
            $keyEditAfterHide = VisibleControls $window.Handle | Where-Object {
                $_.Class -match 'Edit' -and $_.Width -ge 100
            } | Select-Object -First 1
            if (-not $keyEditAfterHide) { throw 'Key edit missing after Hide key' }
            $restoredMask = [ComputerHostWizardProbe]::PasswordMask($keyEditAfterHide.Handle)
            Write-Host "Mask code after Hide: $restoredMask"
            if ($restoredMask -eq 0) {
                throw 'Hide key did not restore password masking'
            }
            Write-Host 'PASS Show/Hide authentication key toggle'
            $keyPath = Join-Path $env:ProgramData 'ComputerHostAgent/control-token'
            if (-not (Test-Path -LiteralPath $keyPath)) { throw 'Power key was not generated' }
            $key = (Get-Content -LiteralPath $keyPath -Raw).Trim()
            if ($key -cnotmatch '^[a-f0-9]{64}$') { throw 'Invalid key format (value withheld)' }
            ClickWizardButton $window.Handle 'Copy authentication key'
            WaitForClipboard $key 'authentication key copying'
            $key = $null
            ClickWizardButton $window.Handle 'Next'
            WaitForWizardText $window.Handle 'Computer Host LAN is installed' 'completed installer page'
        }
        ClickWizardButton $window.Handle 'Finish'
        if ($MonitoringOnly) {
            $info = Invoke-RestMethod http://127.0.0.1:8765/v2/info
            if ($info.power_actions.Count -ne 0) { throw 'Monitoring-only GUI install left privileged commands enabled' }
            if ($SubnetFallback) {
                $addresses = @((Get-NetFirewallRule -Name 'ComputerHostAgent-TCP8765' |
                    Get-NetFirewallAddressFilter).RemoteAddress)
                if ($addresses -notcontains 'LocalSubnet') {
                    throw 'Graphical LocalSubnet fallback did not configure firewall'
                }
            }
            Write-Host 'PASS graphical monitoring-only setup, no key page and LocalSubnet firewall'
        }
        Write-Host 'PASS complete native Windows GUI installation and onboarding workflow'
    }
} finally {
    if ($window) {
        $processId = [ComputerHostWizardProbe]::ProcessId($window.Handle)
        $candidate = Get-Process -Id $processId -ErrorAction SilentlyContinue
        if ($candidate -and $candidate.Path -and
            ($candidate.Path -ieq $setup -or $candidate.ProcessName -like '*setup*')) {
            Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
        }
    }
    if ($proc) {
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
        $proc.Dispose()
    }
}
