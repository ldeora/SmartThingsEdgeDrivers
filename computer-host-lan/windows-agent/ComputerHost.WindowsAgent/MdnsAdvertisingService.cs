using System.Collections.Concurrent;
using System.Runtime.CompilerServices;
using System.Runtime.InteropServices;

[assembly: InternalsVisibleTo("ComputerHost.WindowsAgent.Tests")]

namespace ComputerHost.WindowsAgent;

/// <summary>Native DNS-SD registration, with one outstanding attempt at a time.</summary>
public sealed class MdnsAdvertisingService : BackgroundService
{
    [UnmanagedFunctionPointer(CallingConvention.Winapi)]
    internal delegate void NativeRegistrationCallback(uint status, IntPtr context, IntPtr instance);

    [StructLayout(LayoutKind.Sequential)]
    internal struct RegistrationRequest
    {
        public uint Version;
        public uint InterfaceIndex;
        public IntPtr ServiceInstance;
        public IntPtr Callback;
        public IntPtr Context;
        public IntPtr Credentials;
        [MarshalAs(UnmanagedType.Bool)] public bool UnicastEnabled;
    }


    internal interface INative
    {
        IntPtr Construct(AgentOptions options);
        uint Register(IntPtr request);
        void Free(IntPtr instance);
    }

    internal sealed class Native : INative
    {
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


        public IntPtr Construct(AgentOptions options)
        {
        IntPtr instance;
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
            instance = DnsServiceConstructInstance(serviceName, hostname + ".local", IntPtr.Zero, IntPtr.Zero,
                checked((ushort)options.Port), 0, 0, (uint)keys.Length, keyBlock, valueBlock);
        }
        finally
        {
            foreach (var pointer in keyStrings) Marshal.FreeHGlobal(pointer);
            foreach (var pointer in valueStrings) Marshal.FreeHGlobal(pointer);
            Marshal.FreeHGlobal(keyBlock);
            Marshal.FreeHGlobal(valueBlock);
        }

            return instance;
        }

        public uint Register(IntPtr request) => DnsServiceRegister(request, IntPtr.Zero);
        public void Free(IntPtr instance) => DnsServiceFreeInstance(instance);
    }

    private sealed class Attempt(INative native, ILogger logger, IntPtr instance)
    {
        internal readonly INative Native = native;
        internal readonly ILogger Logger = logger;
        internal readonly IntPtr Instance = instance;
        internal readonly TaskCompletionSource<uint> Completion =
            new(TaskCreationOptions.RunContinuationsAsynchronously);
    }

    private static readonly NativeRegistrationCallback StaticCallback = OnRegistrationCompleted;
    private static readonly ConcurrentDictionary<IntPtr, Attempt> Attempts = new();
    private readonly AgentOptions options;
    private readonly ILogger<MdnsAdvertisingService> logger;
    private readonly INative native;
    private readonly Func<TimeSpan, CancellationToken, Task> delay;
    private readonly TimeSpan pendingWarning;

    public MdnsAdvertisingService(AgentOptions options, ILogger<MdnsAdvertisingService> logger)
        : this(options, logger, new Native(), Task.Delay, TimeSpan.FromSeconds(60)) { }

    internal MdnsAdvertisingService(AgentOptions options, ILogger<MdnsAdvertisingService> logger,
        INative native, Func<TimeSpan, CancellationToken, Task> delay, TimeSpan pendingWarning)
    {
        this.options = options;
        this.logger = logger;
        this.native = native;
        this.delay = delay;
        this.pendingWarning = pendingWarning;
    }

    private static void OnRegistrationCompleted(uint status, IntPtr context, IntPtr instance)
    {
        if (!Attempts.TryGetValue(context, out var attempt)) return;
        try
        {
            // The callback owns its returned copy, not the constructed input.
            if (instance != IntPtr.Zero && instance != attempt.Instance)
                attempt.Native.Free(instance);
        }
        catch (Exception)
        {
            // Never allow an exception to cross the unmanaged callback boundary.
        }
        finally
        {
            attempt.Completion.TrySetResult(status);
        }
    }

    protected override Task ExecuteAsync(CancellationToken stoppingToken) => RunAsync(stoppingToken);

    internal async Task RunAsync(CancellationToken stoppingToken)
    {
        if (!options.DiscoveryEnabled)
        {
            logger.LogWarning("mDNS disabled by HostAgent:DiscoveryEnabled=false (testing only)");
            return;
        }

        var backoff = TimeSpan.FromSeconds(3);
        bool first = true;
        try
        {
            while (!stoppingToken.IsCancellationRequested)
            {
                IntPtr instance;
                try { instance = native.Construct(options); }
                catch (Exception ex)
                {
                    logger.LogWarning("Native DNS-SD construction failed ({Type}); monitoring unaffected", ex.GetType().Name);
                    instance = IntPtr.Zero;
                }
                IntPtr request = IntPtr.Zero;
                uint? status = null;
                if (instance != IntPtr.Zero)
                {
                    var attempt = new Attempt(native, logger, instance);
                    request = Marshal.AllocHGlobal(Marshal.SizeOf<RegistrationRequest>());
                    Marshal.StructureToPtr(new RegistrationRequest
                    {
                        Version = 1, InterfaceIndex = options.DiscoveryInterfaceIndex,
                        ServiceInstance = instance,
                        Callback = Marshal.GetFunctionPointerForDelegate(StaticCallback),
                        Context = request, Credentials = IntPtr.Zero, UnicastEnabled = false
                    }, request, false);
                    Attempts[request] = attempt;
                    uint code;
                    try { code = native.Register(request); }
                    catch (Exception ex)
                    {
                        // Ownership is uncertain. Keep this one attempt rooted until
                        // process exit; do not retry or free potentially live memory.
                        logger.LogWarning("Native DNS-SD call failed ({Type}); discovery may be unavailable, monitoring unaffected", ex.GetType().Name);
                        return;
                    }
                    if (code == 9506)
                    {
                        try
                        {
                            status = await attempt.Completion.Task.WaitAsync(pendingWarning, stoppingToken);
                        }
                        catch (TimeoutException)
                        {
                            logger.LogWarning("Native DNS-SD registration still pending; discovery may be unavailable, monitoring unaffected");
                            status = await attempt.Completion.Task.WaitAsync(stoppingToken);
                        }
                        if (status == 0)
                        {
                            logger.LogInformation("Native Windows DNS-SD registration completed");
                            // Successful registration remains alive until process exit.
                            return;
                        }
                    }
                    else status = code;
                }

                var level = first || backoff.TotalSeconds == 120 ? LogLevel.Warning : LogLevel.Information;
                // DNS_ERROR_RCODE_YXDOMAIN: name already exists.
                if (status == 9006)
                    logger.Log(level, "Native DNS-SD name conflict (status {Status}); retrying in {Seconds}s", status, backoff.TotalSeconds);
                else
                    logger.Log(level, "Native DNS-SD registration failed (status {Status}); retrying in {Seconds}s; monitoring unaffected",
                        status, backoff.TotalSeconds);
                first = false;
                // Give a completed native callback time to unwind before releasing
                // its request and input instance. Cancellation retains the attempt.
                await delay(backoff, stoppingToken);
                if (request != IntPtr.Zero)
                {
                    Attempts.TryRemove(request, out _);
                    Marshal.FreeHGlobal(request);
                    native.Free(instance);
                }
                backoff = TimeSpan.FromSeconds(Math.Min(backoff.TotalSeconds * 2, 120));
            }
        }
        catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested) { }
        catch (Exception ex)
        {
            logger.LogWarning("Native DNS-SD recovery stopped ({Type}); monitoring unaffected", ex.GetType().Name);
        }
    }
}
