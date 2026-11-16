using System.ComponentModel;
using System.Runtime.InteropServices;

namespace ComputerHost.WindowsAgent;

/// <summary>Opt-in best-effort native power operations. No forced application termination.
/// A successful API call acknowledges scheduling, NOT a confirmed power-state transition.</summary>
public static class WindowsPowerOperations
{
    private const int TokenAdjustPrivileges = 0x20;
    private const int TokenQuery = 0x08;
    private const int SePrivilegeEnabled = 0x02;
    private const int ErrorNotAllAssigned = 1300;
    // Planned, unspecified reason (does not falsely label a Windows upgrade).
    private const uint PlannedUserReason = 0x80000000;

    [StructLayout(LayoutKind.Sequential)] private struct Luid { public uint Low; public int High; }
    [StructLayout(LayoutKind.Sequential)] private struct LuidAndAttributes { public Luid Luid; public uint Attributes; }
    [StructLayout(LayoutKind.Sequential)] private struct TokenPrivileges { public uint Count; public LuidAndAttributes Privileges; }

    [DllImport("kernel32.dll")] private static extern IntPtr GetCurrentProcess();
    [DllImport("kernel32.dll", SetLastError = true)] private static extern bool CloseHandle(IntPtr handle);
    [DllImport("advapi32.dll", SetLastError = true)] private static extern bool OpenProcessToken(IntPtr process, int access, out IntPtr token);
    [DllImport("advapi32.dll", EntryPoint = "LookupPrivilegeValueW", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool LookupPrivilegeValue(string? systemName, string name, out Luid luid);
    [DllImport("advapi32.dll", SetLastError = true)]
    private static extern bool AdjustTokenPrivileges(IntPtr token, bool disableAll, ref TokenPrivileges newState,
        uint bufferLength, IntPtr previousState, IntPtr returnLength);
    [DllImport("advapi32.dll", EntryPoint = "InitiateSystemShutdownExW", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool InitiateSystemShutdownEx(string? machine, string? message,
        uint timeoutSeconds, bool forceAppsClosed, bool rebootAfterShutdown, uint reason);
    // Native BOOLEAN is one byte, not Win32 BOOL (four bytes).
    [DllImport("powrprof.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.U1)]
    private static extern bool SetSuspendState([MarshalAs(UnmanagedType.U1)] bool hibernate,
        [MarshalAs(UnmanagedType.U1)] bool force, [MarshalAs(UnmanagedType.U1)] bool disableWakeEvents);

    public static void Execute(string action)
    {
        if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException();
        if (!AgentContract.SupportedPowerActions.Contains(action)) throw new ArgumentOutOfRangeException(nameof(action));
        EnableShutdownPrivilege();
        bool ok = action == "suspend"
            ? SetSuspendState(false, false, false) // DO NOT disable wake events.
            : InitiateSystemShutdownEx(null, "Computer Host LAN requested a " + action,
                15, false, action == "reboot", PlannedUserReason);
        if (!ok) throw new Win32Exception(Marshal.GetLastWin32Error(), "Windows refused " + action);
    }

    private static void EnableShutdownPrivilege()
    {
        if (!OpenProcessToken(GetCurrentProcess(), TokenAdjustPrivileges | TokenQuery, out var token))
            throw new Win32Exception(Marshal.GetLastWin32Error(), "Unable to open service token");
        try
        {
            if (!LookupPrivilegeValue(null, "SeShutdownPrivilege", out var luid))
                throw new Win32Exception(Marshal.GetLastWin32Error(), "Shutdown privilege unavailable");
            var tp = new TokenPrivileges { Count = 1,
                Privileges = new LuidAndAttributes { Luid = luid, Attributes = SePrivilegeEnabled } };
            if (!AdjustTokenPrivileges(token, false, ref tp, 0, IntPtr.Zero, IntPtr.Zero))
                throw new Win32Exception(Marshal.GetLastWin32Error(), "Cannot enable shutdown privilege");
            var error = Marshal.GetLastWin32Error();
            if (error == ErrorNotAllAssigned)
                throw new Win32Exception(error, "Service account lacks SeShutdownPrivilege");
            if (error != 0) throw new Win32Exception(error, "Cannot enable shutdown privilege");
        }
        finally { CloseHandle(token); }
    }
}

public sealed class PowerDispatcher(ILogger<PowerDispatcher> logger)
{
    private int _busy;
    public bool Schedule(string action)
    {
        if (!AgentContract.SupportedPowerActions.Contains(action)) return false;
        if (Interlocked.CompareExchange(ref _busy, 1, 0) != 0) return false;
        _ = Task.Run(async () =>
        {
            try
            {
                // Allow HTTP 202 to reach SmartThings before suspending/shutting down.
                await Task.Delay(TimeSpan.FromSeconds(3));
                WindowsPowerOperations.Execute(action);
                logger.LogInformation("Windows accepted native {Action} API call", action);
            }
            catch (Exception ex)
            {
                logger.LogError(ex, "Native {Action} request failed; verify privileges and powercfg", action);
            }
            finally { Interlocked.Exchange(ref _busy, 0); }
        });
        return true;
    }
}
