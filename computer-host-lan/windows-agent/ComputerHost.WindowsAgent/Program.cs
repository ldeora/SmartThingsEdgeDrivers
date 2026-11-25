using ComputerHost.WindowsAgent;

if (!OperatingSystem.IsWindows())
{
    Console.Error.WriteLine("Windows Host Agent is intended for Windows 11/Windows Server, not Linux.");
    return;
}

var builder = WebApplication.CreateBuilder(args);
builder.Host.UseWindowsService(options => options.ServiceName = "ComputerHostAgent");
var options = builder.Configuration.GetSection("HostAgent").Get<AgentOptions>() ?? new AgentOptions();
if (options.Port is < 1024 or > 65535)
    throw new ArgumentOutOfRangeException(nameof(options.Port), "HostAgent:Port must be between 1024 and 65535.");
builder.WebHost.ConfigureKestrel(server =>
{
    server.ListenAnyIP(options.Port);
    server.Limits.MaxConcurrentConnections = 12;
    server.Limits.MaxRequestBodySize = 0;
    server.Limits.RequestHeadersTimeout = TimeSpan.FromSeconds(5);
    server.Limits.KeepAliveTimeout = TimeSpan.FromSeconds(5);
});
builder.Services.AddSingleton(options);
builder.Services.AddSingleton<PersistentIdentity>();
builder.Services.AddSingleton<BootSession>(sp =>
    new BootSession(sp.GetRequiredService<PersistentIdentity>(), WindowsMetrics.GetTickCount64()));
builder.Services.AddSingleton<WindowsMetrics>();
// Network interfaces can change after boot: evaluate WOL candidates on each info request.
builder.Services.AddTransient<WolMetadata>();
builder.Services.AddSingleton<PowerConfiguration>();
builder.Services.AddSingleton<PowerDispatcher>();
builder.Services.AddHostedService<CpuSamplingService>();
builder.Services.AddHostedService<MdnsAdvertisingService>();
var app = builder.Build();

// Fail at startup if persistent identity is invalid or cannot be written.
_ = app.Services.GetRequiredService<PersistentIdentity>();
_ = app.Services.GetRequiredService<BootSession>();
// Preflight optional power privileges before advertising actions to SmartThings.
_ = app.Services.GetRequiredService<PowerConfiguration>();
app.MapGet("/v2/info", (PersistentIdentity identity, PowerConfiguration power, WolMetadata wol) =>
{
    var build = Environment.OSVersion.Version.Build;
    return Results.Json(new
    {
        protocol = AgentContract.Protocol,
        api_version = AgentContract.ApiVersion,
        agent_version = AgentContract.AgentVersion,
        id = identity.Id,
        hostname = Environment.MachineName,
        platform = AgentContract.Platform,
        os = $"Microsoft Windows (build {build})",
        features = power.Enabled
            ? AgentContract.MonitoringFeatures.Concat(new[] { "power-control" }).ToArray()
            : AgentContract.MonitoringFeatures,
        power_actions = power.Enabled ? AgentContract.SupportedPowerActions : Array.Empty<string>(),
        wol_mac = wol.Mac,
        wol_broadcast = wol.Broadcast,
        wol_interface = wol.InterfaceId
    });
});
app.MapGet("/v2/health", (PersistentIdentity identity, BootSession session) => Results.Json(new
{
    protocol = AgentContract.Protocol,
    api_version = AgentContract.ApiVersion,
    platform = AgentContract.Platform,
    id = identity.Id,
    status = "running",
    boot_id = session.BootId,
    uptime_seconds = Math.Round(WindowsMetrics.GetTickCount64() / 1000.0, 1)
}));
app.MapGet("/v2/metrics", (PersistentIdentity identity, BootSession session, WindowsMetrics metrics) =>
    Results.Json(metrics.Read(identity.Id, session.BootId)));

// Exact Linux-compatible challenge/signature protocol; power remains disabled by default.
app.MapGet("/v2/challenge", (HttpContext context, PersistentIdentity identity, PowerConfiguration power) =>
{
    if (!power.Enabled || power.Authentication is null) return Results.StatusCode(403);
    var remote = context.Connection.RemoteIpAddress?.ToString() ?? "unknown";
    var nonce = power.Authentication.Issue(remote);
    if (nonce is null) return Results.StatusCode(429);
    context.Response.Headers["Cache-Control"] = "no-store";
    return Results.Json(new { protocol = AgentContract.Protocol, api_version = AgentContract.ApiVersion,
        platform = AgentContract.Platform, id = identity.Id, nonce, expires_in = 30 });
});
app.MapPost("/v2/power/{action}", (string action, HttpContext context, PersistentIdentity identity,
    PowerConfiguration power, PowerDispatcher dispatcher) =>
{
    if (!power.Enabled || power.Authentication is null) return Results.StatusCode(403);
    if (!AgentContract.SupportedPowerActions.Contains(action)) return Results.NotFound();
    if (context.Request.ContentLength is > 0 || context.Request.Headers.ContainsKey("Transfer-Encoding"))
        return Results.BadRequest(new { error = "body not allowed" });
    var remote = context.Connection.RemoteIpAddress?.ToString() ?? "unknown";
    var nonce = context.Request.Headers["X-ComputerHost-Nonce"].ToString();
    var signature = context.Request.Headers["X-ComputerHost-Signature"].ToString();
    if (!power.Authentication.Authenticate(action, nonce, signature, remote)) return Results.Unauthorized();
    var dispatch = dispatcher.TrySchedule(action);
    if (dispatch == PowerDispatchResult.Busy)
        return Results.Conflict(new { error = "power operation already pending" });
    if (dispatch == PowerDispatchResult.ShutdownInProgress)
        return Results.Conflict(new { error = "Windows shutdown or reboot is already in progress" });
    if (dispatch != PowerDispatchResult.Accepted)
        return Results.StatusCode(503);
    context.Response.Headers["Cache-Control"] = "no-store";
    return Results.Json(new { protocol = AgentContract.Protocol, api_version = AgentContract.ApiVersion,
        platform = AgentContract.Platform, id = identity.Id, accepted = true, action }, statusCode: 202);
});
app.MapFallback(() => Results.NotFound());

app.Logger.LogInformation("Windows Host Agent {Version} (power opt-in: {Power}, available: {Available}), port {Port}",
    AgentContract.AgentVersion, options.EnablePowerControl,
    app.Services.GetRequiredService<PowerConfiguration>().Enabled, options.Port);
await app.RunAsync();
