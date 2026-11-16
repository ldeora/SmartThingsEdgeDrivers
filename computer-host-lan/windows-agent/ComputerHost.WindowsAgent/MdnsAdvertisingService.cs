using System.Runtime.InteropServices;

namespace ComputerHost.WindowsAgent;

/// <summary>
/// Registers native DNS-SD (_computerhost._tcp.local) using dnsapi.dll. The registration is
/// asynchronous and bound to the process lifetime. No Bonjour/third-party daemon is required.
/// On shutdown the process automatically drops the registration; per Microsoft the native API
/// unregisters services when the calling process exits.
/// The unmanaged request and instance intentionally live until process exit, avoiding a callback
/// use-after-free during asynchronous service shutdown. This is one allocation per service process.
/// </summary>
public sealed class MdnsAdvertisingService(AgentOptions options,
    ILogger<MdnsAdvertisingService> logger) : BackgroundService
{
    [UnmanagedFunctionPointer(CallingConvention.Winapi)]
    private delegate void NativeRegistrationCallback(uint status, IntPtr context, IntPtr instance);

    [StructLayout(LayoutKind.Sequential)]
    private struct RegistrationRequest
    {
        public uint Version;
        public uint InterfaceIndex;
        public IntPtr ServiceInstance;
        public IntPtr Callback;
        public IntPtr Context;
        public IntPtr Credentials;
        [MarshalAs(UnmanagedType.Bool)] public bool UnicastEnabled;
    }

    private static readonly NativeRegistrationCallback StaticCallback = OnRegistrationCompleted;
    private static readonly System.Collections.Concurrent.ConcurrentDictionary<IntPtr, ILogger> Loggers = new();
    private IntPtr _request;
    private IntPtr _instance;

    [DllImport("dnsapi.dll", CharSet = CharSet.Unicode, ExactSpelling = true)]
    private static extern IntPtr DnsServiceConstructInstance(
        [MarshalAs(UnmanagedType.LPWStr)] string serviceName,
        [MarshalAs(UnmanagedType.LPWStr)] string hostName,
        IntPtr ip4, IntPtr ip6,
        ushort port, ushort priority, ushort weight,
        uint propertyCount, IntPtr keys, IntPtr values);

    [DllImport("dnsapi.dll", ExactSpelling = true)]
    private static extern uint DnsServiceRegister(IntPtr request, IntPtr cancel);

    [DllImport("dnsapi.dll", ExactSpelling = true)]
    private static extern void DnsServiceFreeInstance(IntPtr instance);

    private static void OnRegistrationCompleted(uint status, IntPtr context, IntPtr instance)
    {
        try
        {
            if (Loggers.TryGetValue(context, out var log))
            {
                if (status == 0) log.LogInformation("Native Windows DNS-SD registration completed");
                else log.LogWarning("Native Windows DNS-SD registration callback status {Status}", status);
            }
        }
        finally
        {
            if (instance != IntPtr.Zero) DnsServiceFreeInstance(instance);
        }
    }

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        if (!options.DiscoveryEnabled)
        {
            logger.LogWarning("mDNS disabled by HostAgent:DiscoveryEnabled=false (testing only)");
            return;
        }
        var hostname = Environment.MachineName;
        // DNS-SD TXT includes the same protocol marker and platform as the Linux Avahi service.
        var keys = new[] { "platform", "agent", "api" };
        var values = new[] { "windows", AgentContract.Protocol, "2" };
        var keyStrings = keys.Select(Marshal.StringToHGlobalUni).ToArray();
        var valueStrings = values.Select(Marshal.StringToHGlobalUni).ToArray();
        var keyBlock = Marshal.AllocHGlobal(IntPtr.Size * keys.Length);
        var valueBlock = Marshal.AllocHGlobal(IntPtr.Size * values.Length);
        try
        {
            for (var i = 0; i < keys.Length; i++)
            {
                Marshal.WriteIntPtr(keyBlock, i * IntPtr.Size, keyStrings[i]);
                Marshal.WriteIntPtr(valueBlock, i * IntPtr.Size, valueStrings[i]);
            }
            // Instance name must be a fully-qualified service instance (not just the type).
            var serviceName = $"Computer Host Agent (Windows) on {hostname}._computerhost._tcp.local";
            var hostName = hostname + ".local";
            _instance = DnsServiceConstructInstance(serviceName, hostName, IntPtr.Zero, IntPtr.Zero,
                checked((ushort)options.Port), 0, 0, (uint)keys.Length, keyBlock, valueBlock);
        }
        finally
        {
            foreach (var pointer in keyStrings) Marshal.FreeHGlobal(pointer);
            foreach (var pointer in valueStrings) Marshal.FreeHGlobal(pointer);
            Marshal.FreeHGlobal(keyBlock);
            Marshal.FreeHGlobal(valueBlock);
        }
        if (_instance == IntPtr.Zero)
        {
            logger.LogError("DnsServiceConstructInstance failed. HTTP monitoring remains available; mDNS discovery is unavailable.");
            return;
        }
        _request = Marshal.AllocHGlobal(Marshal.SizeOf<RegistrationRequest>());
        var req = new RegistrationRequest
        {
            Version = 1, InterfaceIndex = options.DiscoveryInterfaceIndex,
            ServiceInstance = _instance,
            Callback = Marshal.GetFunctionPointerForDelegate(StaticCallback),
            Context = _request, Credentials = IntPtr.Zero,
            UnicastEnabled = false
        };
        Marshal.StructureToPtr(req, _request, false);
        Loggers.TryAdd(_request, logger);
        var code = DnsServiceRegister(_request, IntPtr.Zero);
        if (code != 9506) // DNS_REQUEST_PENDING, normal asynchronous success.
        {
            logger.LogError("DnsServiceRegister returned {Code}; auto discovery unavailable", code);
            Loggers.TryRemove(_request, out _);
            return;
        }
        logger.LogInformation("Advertising {Service} TCP {Port}; interface index {Interface}",
            AgentContract.ServiceType, options.Port, options.DiscoveryInterfaceIndex);
        try { await Task.Delay(Timeout.InfiniteTimeSpan, stoppingToken); }
        catch (OperationCanceledException) { }
        // Native registration lifetime ends when service process exits, per Microsoft.
        // Deliberately no asynchronous cancellation/free before exit to avoid callback races.
    }
}
