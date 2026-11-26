using System.Runtime.InteropServices;
using ComputerHost.WindowsAgent;
using Microsoft.Extensions.Logging.Abstractions;

internal static class MdnsRetryTests
{
    private sealed class Fake : MdnsAdvertisingService.INative
    {
        internal int Allocations, Frees, Registrations;
        internal uint Immediate = 9506, CallbackStatus = 5;
        internal bool Complete = true;
        internal IntPtr LastRequest;
        public IntPtr Construct(AgentOptions options)
        {
            Allocations++;
            return new IntPtr(Allocations);
        }
        public uint Register(IntPtr request)
        {
            Registrations++;
            LastRequest = request;
            if (Immediate == 9506 && Complete)
            {
                var data = Marshal.PtrToStructure<MdnsAdvertisingService.RegistrationRequest>(request);
                Marshal.GetDelegateForFunctionPointer<MdnsAdvertisingService.NativeRegistrationCallback>(data.Callback)
                    (CallbackStatus, data.Context, IntPtr.Zero);
            }
            return Immediate;
        }
        public void Free(IntPtr instance) => Frees++;
    }

    private static void Check(bool condition, string message)
    {
        if (!condition) throw new Exception("FAILED DNS-SD: " + message);
        Console.WriteLine("PASS DNS-SD: " + message);
    }

    internal static async Task Run()
    {
        foreach (uint immediate in new uint[] { 9506, 5 })
        {
            using var stop = new CancellationTokenSource();
            var fake = new Fake { Immediate = immediate };
            var delays = new List<double>();
            using var service = new MdnsAdvertisingService(new AgentOptions { DiscoveryEnabled = true },
                NullLogger<MdnsAdvertisingService>.Instance, fake, (duration, token) =>
                {
                    Check(fake.Allocations - fake.Frees == 1, "failed attempt retained during backoff");
                    delays.Add(duration.TotalSeconds);
                    if (delays.Count == 9) stop.Cancel();
                    return token.IsCancellationRequested ? Task.FromCanceled(token) : Task.CompletedTask;
                }, TimeSpan.FromSeconds(1));
            await service.RunAsync(stop.Token).WaitAsync(TimeSpan.FromSeconds(5));
            Check(delays.SequenceEqual(new double[] { 3, 6, 12, 24, 48, 96, 120, 120, 120 }), "bounded backoff");
            Check(fake.Registrations == 9 && fake.Allocations - fake.Frees == 1, "bounded outstanding attempts");
        }
        var success = new Fake { CallbackStatus = 0 };
        using (var service = new MdnsAdvertisingService(new AgentOptions { DiscoveryEnabled = true },
            NullLogger<MdnsAdvertisingService>.Instance, success,
            (_, _) => throw new Exception("unexpected retry"), TimeSpan.FromSeconds(1)))
        {
            await service.RunAsync(CancellationToken.None).WaitAsync(TimeSpan.FromSeconds(5));
            Check(success.Registrations == 1 && success.Frees == 0, "early successful callback retains registration");
        }
        var pending = new Fake { Complete = false };
        using (var stop = new CancellationTokenSource())
        using (var service = new MdnsAdvertisingService(new AgentOptions { DiscoveryEnabled = true },
            NullLogger<MdnsAdvertisingService>.Instance, pending,
            (_, _) => throw new Exception("unexpected retry"), TimeSpan.FromMilliseconds(10)))
        {
            var run = service.RunAsync(stop.Token);
            await Task.Delay(50);
            stop.Cancel();
            await run.WaitAsync(TimeSpan.FromSeconds(5));
            Check(pending.Registrations == 1 && pending.Frees == 0, "pending timeout and cancellation retain native attempt");
        }
        var disabled = new Fake();
        using (var service = new MdnsAdvertisingService(new AgentOptions { DiscoveryEnabled = false },
            NullLogger<MdnsAdvertisingService>.Instance, disabled, Task.Delay, TimeSpan.FromSeconds(1)))
        {
            await service.RunAsync(CancellationToken.None);
            Check(disabled.Allocations == 0, "disabled discovery performs no native calls");
        }
    }
}
