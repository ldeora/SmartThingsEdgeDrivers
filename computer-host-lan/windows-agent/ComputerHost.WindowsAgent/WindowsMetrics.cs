using System.Runtime.InteropServices;

namespace ComputerHost.WindowsAgent;

public sealed class WindowsMetrics
{
    private readonly object _gate = new();
    private CpuSample? _prior;
    private double? _currentCpu;

    [StructLayout(LayoutKind.Sequential)]
    private struct WinFileTime { public uint Low; public uint High; public readonly ulong Value => ((ulong)High << 32) | Low; }

    [StructLayout(LayoutKind.Sequential)]
    private struct MemoryStatus
    {
        public uint Length;
        public uint MemoryLoad;
        public ulong TotalPhys;
        public ulong AvailPhys;
        public ulong TotalPageFile;
        public ulong AvailPageFile;
        public ulong TotalVirtual;
        public ulong AvailVirtual;
        public ulong AvailExtendedVirtual;
    }

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool GetSystemTimes(out WinFileTime idle, out WinFileTime kernel, out WinFileTime user);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool GlobalMemoryStatusEx(ref MemoryStatus status);

    [DllImport("kernel32.dll")]
    public static extern ulong GetTickCount64();

    public readonly record struct CpuSample(ulong Idle, ulong Kernel, ulong User);

    /// <summary>Kernel includes Idle. Compare deltas, never raw Windows cumulative counters.</summary>
    public static double? CpuPercent(CpuSample? before, CpuSample after)
    {
        if (before is not CpuSample first || after.Idle < first.Idle ||
            after.Kernel < first.Kernel || after.User < first.User) return null;
        var busyTotal = (after.Kernel - first.Kernel) + (after.User - first.User);
        var idleDelta = after.Idle - first.Idle;
        if (busyTotal == 0 || idleDelta > busyTotal) return null;
        return Math.Round(Math.Clamp(100.0 * (busyTotal - idleDelta) / busyTotal, 0, 100), 1);
    }

    public void SampleCpu()
    {
        if (!GetSystemTimes(out var idle, out var kernel, out var user))
            throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error(), "GetSystemTimes failed");
        var sample = new CpuSample(idle.Value, kernel.Value, user.Value);
        lock (_gate)
        {
            _currentCpu = CpuPercent(_prior, sample);
            _prior = sample;
        }
    }

    public object Read(string id, string bootId)
    {
        var mem = new MemoryStatus { Length = (uint)Marshal.SizeOf<MemoryStatus>() };
        if (!GlobalMemoryStatusEx(ref mem))
            throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error(), "GlobalMemoryStatusEx failed");
        double? disk = null;
        try
        {
            var windowsPath = Environment.GetFolderPath(Environment.SpecialFolder.Windows);
            var root = Path.GetPathRoot(windowsPath);
            if (!string.IsNullOrEmpty(root))
            {
                var drive = new DriveInfo(root);
                if (drive.IsReady && drive.TotalSize > 0)
                    disk = Math.Round(100.0 * (drive.TotalSize - drive.AvailableFreeSpace) / drive.TotalSize, 1);
            }
        }
        catch (IOException) { /* Unknown metric is not zero. */ }
        catch (UnauthorizedAccessException) { /* Unknown metric is not zero. */ }
        double? cpu;
        lock (_gate) cpu = _currentCpu;
        return new
        {
            protocol = AgentContract.Protocol,
            api_version = AgentContract.ApiVersion,
            platform = AgentContract.Platform,
            id,
            cpu_usage_percent = cpu,
            memory_usage_percent = Math.Round(100.0 * (mem.TotalPhys - mem.AvailPhys) / Math.Max(1.0, mem.TotalPhys), 1),
            memory_total_bytes = mem.TotalPhys,
            disk_root_usage_percent = disk,
            cpu_temperature_c = (double?)null,
            cpu_temperature_label = (string?)null,
            uptime_seconds = Math.Round(GetTickCount64() / 1000.0, 1),
            boot_id = bootId
        };
    }
}

public sealed class CpuSamplingService(WindowsMetrics metrics, ILogger<CpuSamplingService> logger) : BackgroundService
{
    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        using var timer = new PeriodicTimer(TimeSpan.FromSeconds(2));
        while (!stoppingToken.IsCancellationRequested)
        {
            try { metrics.SampleCpu(); }
            catch (Exception ex) { logger.LogWarning(ex, "Windows CPU sample unavailable"); }
            try { if (!await timer.WaitForNextTickAsync(stoppingToken)) break; }
            catch (OperationCanceledException) { break; }
        }
    }
}
