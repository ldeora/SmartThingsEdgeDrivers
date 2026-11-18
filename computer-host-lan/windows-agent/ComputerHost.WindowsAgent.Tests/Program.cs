using System.Text.Json;
using ComputerHost.WindowsAgent;

static void Assert(bool condition, string message)
{
    if (!condition) throw new Exception("FAILED: " + message);
    Console.WriteLine("PASS " + message);
}

Assert(AgentContract.Protocol == "computer-host-agent", "protocol name");
Assert(AgentContract.ApiVersion == 2 && AgentContract.Platform == "windows", "v2 Windows envelope");
Assert(AgentContract.ServiceType == "_computerhost._tcp.local", "same mDNS service as Linux");
Assert(AgentContract.SupportedPowerActions.SequenceEqual(new[] { "reboot", "shutdown", "suspend" }), "opt-in power actions contract");
Assert(AgentContract.MonitoringFeatures.SequenceEqual(new[] { "health", "metrics", "wol-metadata" }), "monitoring capabilities");
Assert(JsonSerializer.Serialize(AgentContract.Envelope("x")).Contains("\"api_version\":2"), "protocol JSON snake_case");

// Cross-language vector from shared/contract-v2.json, verified against Linux Python and Lua.
var vector = new PowerAuthentication(string.Concat(Enumerable.Repeat("01", 32)));
Assert(vector.Sign("reboot", new string('a', 48)) ==
    "bee90235a4e0de60ce651fac03e27ed024fa49ed822feb81943deb96283843e2",
    "Linux v2 HMAC cross-language test vector");
var key = string.Concat(Enumerable.Repeat("ab", 32));
var auth = new PowerAuthentication(key);
var nonce = auth.Issue("192.0.2.11")!;
Assert(nonce.Length == 48, "24-byte cryptographic challenge");
var sig = auth.Sign("reboot", nonce);
Assert(auth.Authenticate("reboot", nonce, sig, "192.0.2.11"), "valid HMAC for reboot");
Assert(!auth.Authenticate("reboot", nonce, sig, "192.0.2.11"), "replay is rejected");
var another = auth.Issue("192.0.2.11")!;
Assert(!auth.Authenticate("shutdown", another, auth.Sign("reboot", another), "192.0.2.11"), "signature bound to action");
Assert(!auth.Authenticate("reboot", another, auth.Sign("reboot", another), "192.0.2.12"), "challenge bound to client");
Assert(auth.Authenticate("reboot", another, auth.Sign("reboot", another), "192.0.2.11"), "invalid proof doesn't consume challenge");
var throttle = new PowerAuthentication(key);
for (var i = 0; i < PowerAuthentication.MaxChallengesPerMinute; i++)
    Assert(throttle.Issue("192.0.2.44") is not null, "challenge within rate limit " + i);
Assert(throttle.Issue("192.0.2.44") is null, "challenge rate limit");
Assert(!new PowerConfiguration(new AgentOptions { EnablePowerControl = false },
    new PersistentIdentity(new AgentOptions { StateDirectory = Path.Combine(Path.GetTempPath(), "computerhost-disabled-" + Guid.NewGuid().ToString("N")) })).Enabled,
    "monitoring mode remains default");

var a = new WindowsMetrics.CpuSample(1000, 5000, 5000);
var b = new WindowsMetrics.CpuSample(1200, 5600, 5400);
Assert(WindowsMetrics.CpuPercent(a, b) == 80, "CPU delta excludes idle kernel time");
Assert(WindowsMetrics.CpuPercent(null, b) is null, "CPU first sample null");
Assert(WindowsMetrics.CpuPercent(b, a) is null, "CPU backwards time rejected");
Assert(BootSession.IsSameBoot(1000, 1119), "boot estimate within tolerance preserved");
Assert(!BootSession.IsSameBoot(1000, 1400), "genuine kernel restart changes boot ID");

var temp = Path.Combine(Path.GetTempPath(), "computerhost-agent-tests-" + Guid.NewGuid().ToString("N"));
try
{
    var cfg = new AgentOptions { StateDirectory = temp };
    var id1 = new PersistentIdentity(cfg);
    var id2 = new PersistentIdentity(cfg);
    Assert(id1.Id == id2.Id && Guid.TryParse(id1.Id, out _), "persistent identity survives process reinitialization");
    var boot1 = new BootSession(id1, 400000);
    var boot2 = new BootSession(id2, 400100);
    Assert(boot1.BootId == boot2.BootId, "boot session survives service restart");
    var boot3 = new BootSession(id2, 800000);
    Assert(boot3.BootId != boot2.BootId, "boot session rotates after new kernel startup");
    File.WriteAllText(Path.Combine(temp, "installation-id"), "corrupt");
    bool threw = false;
    try { _ = new PersistentIdentity(cfg); } catch (InvalidDataException) { threw = true; }
    Assert(threw, "corrupt identity fails closed");
}
finally { if (Directory.Exists(temp)) Directory.Delete(temp, recursive: true); }

if (OperatingSystem.IsWindows())
{
    var metrics = new WindowsMetrics();
    metrics.SampleCpu();
    var json = JsonSerializer.Serialize(metrics.Read(Guid.NewGuid().ToString(), Guid.NewGuid().ToString()));
    using var doc = JsonDocument.Parse(json);
    var root = doc.RootElement;
    var memoryTotal = root.GetProperty("memory_total_bytes").GetUInt64();
    var memoryUsed = root.GetProperty("memory_used_bytes").GetUInt64();
    var memoryAvailable = root.GetProperty("memory_available_bytes").GetUInt64();
    Assert(memoryTotal > 0, "Win32 physical RAM metrics");
    Assert(memoryUsed <= memoryTotal && memoryAvailable <= memoryTotal &&
           memoryTotal - memoryAvailable == memoryUsed,
           "Physical RAM accounting uses available memory");
    var driveTotal = root.GetProperty("disk_root_total_bytes").GetInt64();
    var driveUsed = root.GetProperty("disk_root_used_bytes").GetInt64();
    var driveAvailable = root.GetProperty("disk_root_available_bytes").GetInt64();
    Assert(driveTotal > 0, "Windows system drive total bytes");
    // Disk quotas mean used + available need not equal TotalSize.
    Assert(driveUsed >= 0 && driveUsed <= driveTotal &&
           driveAvailable >= 0 && driveAvailable <= driveTotal,
           "Windows system drive allocated and available bytes");
    Assert(root.GetProperty("disk_root_usage_percent").GetDouble() >= 0, "Windows system drive usage percentage");
    Assert(root.GetProperty("uptime_seconds").GetDouble() >= 0, "Windows uptime metrics");
    Assert(root.GetProperty("cpu_temperature_c").ValueKind == JsonValueKind.Null, "no fabricated CPU temperature");
    Assert(!root.TryGetProperty("load_1m", out _), "no fabricated Linux load on Windows");
}

Console.WriteLine("All Windows Host Agent contract tests passed.");
