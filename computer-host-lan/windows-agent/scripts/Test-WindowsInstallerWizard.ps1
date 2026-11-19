# Smoke-test actual HWND wizard controls on a Windows CI runner.
# This intentionally never presses Install or reads agent credentials.
# Hosted runners may lack a usable GUI desktop: failures must be reported,
# not silently treated as a completed UI test.
[CmdletBinding()]
param([Parameter(Mandatory)][string]$SetupExecutable)
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
    [DllImport("user32.dll")] private static extern IntPtr SendMessage(IntPtr h, uint m, IntPtr w, IntPtr l);
    [DllImport("user32.dll")] private static extern uint GetWindowThreadProcessId(IntPtr h, out uint processId);
    public static Item Read(IntPtr h) {
        var t = new StringBuilder(1024);
        var c = new StringBuilder(256);
        GetWindowText(h, t, t.Capacity);
        GetClassName(h, c, c.Capacity);
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
    public static int ProcessId(IntPtr hwnd) {
        uint id; GetWindowThreadProcessId(hwnd, out id); return (int)id;
    }
}
'@ -ErrorAction Stop

$setup = (Resolve-Path -LiteralPath $SetupExecutable).Path
Write-Host "Wizard GUI smoke test (never installs): $setup"
$proc = $null
$window = $null
try {
    $proc = Start-Process -FilePath $setup -PassThru
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

    $next = $children | Where-Object {
        $_.Visible -and $_.Class -match 'Button' -and $_.Text -match 'Next'
    } | Select-Object -First 1
    if (-not $next) { throw 'Welcome Next button is not visible' }
    [ComputerHostWizardProbe]::Click($next.Handle)

    $onHub = $false
    for ($attempt = 0; $attempt -lt 70; $attempt++) {
        $children = @([ComputerHostWizardProbe]::Children($window.Handle))
        if (@($children | Where-Object {
            $_.Visible -and $_.Text -match 'SmartThings hub \(automatically detected'
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
    $rescan = $children | Where-Object { $_.Visible -and $_.Text -match 'Search again' } | Select-Object -First 1
    if (-not $rescan) { throw 'Search again button not visible' }
    Write-Host 'PASS Search again button visible'
    Write-Host 'PASS graphical Welcome and hub selector smoke test'
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
