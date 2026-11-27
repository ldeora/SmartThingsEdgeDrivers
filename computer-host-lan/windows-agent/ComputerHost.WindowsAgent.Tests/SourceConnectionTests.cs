using System.Net;
using System.Net.Sockets;
using System.Text;
using ComputerHost.WindowsAgent;
using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Connections;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Hosting.Server;
using Microsoft.AspNetCore.Hosting.Server.Features;
using Microsoft.Extensions.DependencyInjection;

internal static class SourceConnectionTests
{
    private static void Check(bool condition, string message)
    {
        if (!condition) throw new Exception("FAILED connection admission: " + message);
        Console.WriteLine("PASS connection admission: " + message);
    }

    internal static async Task Run()
    {
        // Direct pipeline test: mapped and native IPv4 share one quota.
        var limit = new SourceConnectionLimit();
        var release = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var entered = 0;
        var pipeline = limit.Wrap(async _ => { Interlocked.Increment(ref entered); await release.Task; });
        var contexts = Enumerable.Range(0, 4).Select(i => new DefaultConnectionContext
        {
            RemoteEndPoint = new IPEndPoint(IPAddress.Parse(i % 2 == 0 ? "192.0.2.1" : "::ffff:192.0.2.1"), 10000+i)
        }).ToArray();
        var tasks = contexts.Select(pipeline.Invoke).ToArray();
        var excess = new DefaultConnectionContext { RemoteEndPoint = new IPEndPoint(IPAddress.Parse("192.0.2.1"), 10010) };
        await pipeline(excess).WaitAsync(TimeSpan.FromSeconds(2));
        Check(entered == 4, "IPv4 and mapped IPv6 share four slots");
        release.SetResult();
        await Task.WhenAll(tasks);
        await pipeline(excess);
        Check(entered == 5, "released slot is reusable");
        foreach (var context in contexts) await context.DisposeAsync();
        await excess.DisposeAsync();

        // Real Kestrel TCP pipeline with incomplete HTTP requests. A test-only
        // outer middleware signals arrival; the production limiter is unchanged.
        var builder = WebApplication.CreateBuilder();
        var realLimit = new SourceConnectionLimit();
        var arrivals = System.Threading.Channels.Channel.CreateUnbounded<bool>();
        var admissions = System.Threading.Channels.Channel.CreateUnbounded<bool>();
        builder.WebHost.ConfigureKestrel(server =>
        {
            server.Limits.MaxConcurrentConnections = 12;
            server.Limits.RequestHeadersTimeout = TimeSpan.FromSeconds(20);
            server.Listen(IPAddress.Loopback, 0, listen =>
            {
                listen.Use(next => async connection =>
                {
                    arrivals.Writer.TryWrite(true);
                    await next(connection);
                });
                listen.Use(realLimit.Wrap);
                listen.Use(next => async connection =>
                {
                    admissions.Writer.TryWrite(true);
                    await next(connection);
                });
            });
        });
        await using var app = builder.Build();
        app.MapGet("/health", () => "ok");
        await app.StartAsync();
        var uri = new Uri(app.Services.GetRequiredService<IServer>().Features.Get<IServerAddressesFeature>()!.Addresses.Single());
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(15));
        var held = new List<TcpClient>();
        async Task<TcpClient> Connect()
        {
            var client = new TcpClient(AddressFamily.InterNetwork);
            try
            {
                await client.ConnectAsync(IPAddress.Loopback, uri.Port, timeout.Token);
                await arrivals.Reader.ReadAsync(timeout.Token);
                return client;
            }
            catch { client.Dispose(); throw; }
        }
        try
        {
            for (int i = 0; i < 4; i++)
            {
                var client = await Connect();
                held.Add(client);
                await admissions.Reader.ReadAsync(timeout.Token);
                await client.GetStream().WriteAsync(Encoding.ASCII.GetBytes("GET /health"), timeout.Token);
            }
            using (var rejected = await Connect())
            {
                bool closed;
                try { closed = await rejected.GetStream().ReadAsync(new byte[1], timeout.Token) == 0; }
                catch (IOException) { closed = true; }
                catch (SocketException) { closed = true; }
                Check(closed && !admissions.Reader.TryRead(out _), "fifth incomplete connection rejected before HTTP");
            }
            held[0].Dispose();
            // Wait for actual TCP disconnect cleanup; retry boundedly.
            bool recovered = false;
            for (int i = 0; i < 20 && !recovered; i++)
            {
                using var client = new HttpClient { Timeout = TimeSpan.FromSeconds(5) };
                try { recovered = await client.GetStringAsync(new Uri(uri, "/health"), timeout.Token) == "ok"; }
                catch (HttpRequestException) { }
                catch (TaskCanceledException) when (!timeout.IsCancellationRequested) { }
                if (!recovered) await Task.Delay(100, timeout.Token);
            }
            Check(recovered, "real listener recovers after disconnect");
        }
        finally
        {
            foreach (var client in held) client.Dispose();
            await app.StopAsync();
        }
    }
}
