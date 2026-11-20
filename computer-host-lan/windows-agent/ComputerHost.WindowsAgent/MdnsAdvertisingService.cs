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
            if (instance != IntPtr.Zero)
            {
                try { DnsServiceFreeInstance(instance); }
                catch (Exception) { /* A native callback must not crash the HTTP agent. */ }
            }
        }
    }

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        if (!options.DiscoveryEnabled)
        {
            logger.LogWarning("mDNS disabled by HostAgent:DiscoveryEnabled=false (testing only)");
            return;
        }
        // DNS-SD can fail temporarily while Windows initializes the network.
        // Such failures must never bring down the HTTP monitoring service.
        var delay = TimeSpan.FromSeconds(3);
        while (!stoppingToken.IsCancellationRequested)
        {
            try
            {
                if (TryRegister())
                {
                    try { await Task.Delay(Timeout.InfiniteTimeSpan, stoppingToken); }
                    catch (OperationCanceledException) { }
                    return;
                }
            }
            catch (Exception ex) when (!stoppingToken.IsCancellationRequested)
            {
                logger.LogWarning(ex, "Native mDNS registration failed; HTTP monitoring remains available");
            }
            try { await Task.Delay(delay, stoppingToken); }
            catch (OperationCanceledException) { return; }
            delay = TimeSpan.FromSeconds(Math.Min(delay.TotalSeconds * 2, 120));
        }
    }

    private bool TryRegister()
    {
        var hostname = Environment.MachineName;
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
            var serviceName = $"Computer Host Agent (Windows) on {hostname}._computerhost._tcp.local";
            _instance = DnsServiceConstructInstance(serviceName, hostname + ".local", IntPtr.Zero, IntPtr.Zero,
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
            logger.LogWarning("DnsServiceConstructInstance returned null; retrying without disrupting HTTP");
            return false;
        }
        _request = Marshal.AllocHGlobal(Marshal.SizeOf<RegistrationRequest>());
        var request = new RegistrationRequest
        {
            Version = 1, InterfaceIndex = options.DiscoveryInterfaceIndex,
            ServiceInstance = _instance,
            Callback = Marshal.GetFunctionPointerForDelegate(StaticCallback),
            Context = _request, Credentials = IntPtr.Zero,
            UnicastEnabled = false
        };
        Marshal.StructureToPtr(request, _request, false);
        Loggers.TryAdd(_request, logger);
        uint code;
        try { code = DnsServiceRegister(_request, IntPtr.Zero); }
        catch
        {
            // Do not free request/instance if an asynchronous native callback
            // may still hold them. The bounded allocation survives until exit.
            throw;
        }
        if (code != 9506) // DNS_REQUEST_PENDING
        {
            logger.LogWarning("DnsServiceRegister returned {Code}; retrying mDNS discovery", code);
            Loggers.TryRemove(_request, out _);
            // A synchronous registration failure has not handed ownership to
            // the DNS-SD callback. Release temporary unmanaged allocations.
            Marshal.FreeHGlobal(_request);
            DnsServiceFreeInstance(_instance);
            _request = IntPtr.Zero;
            _instance = IntPtr.Zero;
            return false;
        }
        logger.LogInformation("Advertising {Service} TCP {Port}; interface index {Interface}",
            AgentContract.ServiceType, options.Port, options.DiscoveryInterfaceIndex);
        // Native request and instance remain alive for callbacks until process exit.
        return true;
    }
}
