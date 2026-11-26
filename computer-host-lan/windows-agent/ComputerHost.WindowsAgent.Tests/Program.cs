using System.Text.Json;
using System.ComponentModel;
using System.Security.AccessControl;
using System.Security.Principal;
using Microsoft.Extensions.Logging.Abstractions;
using ComputerHost.WindowsAgent;

static void Assert(bool condition, string message)
{
    if (!condition) throw new Exception("FAILED: " + message);
    Console.WriteLine("PASS " + message);
}

// Compare the fixture's actual ACEs and inheritance protection, not SDDL
// control flags (Windows can set the auto-inherited flag when writing a DACL).
[System.Runtime.Versioning.SupportedOSPlatform("windows")]
static string AccessRules(FileSystemSecurity security)
{
    var rules = new List<string>();
    foreach (FileSystemAccessRule rule in security.GetAccessRules(true, true, typeof(SecurityIdentifier)))
        rules.Add($"{rule.IdentityReference}:{rule.AccessControlType}:{(int)rule.FileSystemRights}:" +
                  $"{rule.InheritanceFlags}:{rule.PropagationFlags}:{rule.IsInherited}");
    rules.Sort(StringComparer.Ordinal);
    return (security.AreAccessRulesProtected ? "P|" : "|") + string.Join(";", rules);
}

static void AssertRestoredRules(string expected, string actual, string message)
{
    Assert(expected == actual, expected == actual ? message :
        $"{message}\nExpected: {expected}\nObserved: {actual}");
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

var a = new WindowsMetrics.CpuSample(1000, 5000, 5000);
var b = new WindowsMetrics.CpuSample(1200, 5600, 5400);
Assert(WindowsMetrics.CpuPercent(a, b) == 80, "CPU delta excludes idle kernel time");
Assert(WindowsMetrics.CpuPercent(null, b) is null, "CPU first sample null");
Assert(WindowsMetrics.CpuPercent(b, a) is null, "CPU backwards time rejected");
Assert(WolMetadata.LooksVirtualAdapter("vEthernet (WSL)", "Hyper-V Virtual Ethernet Adapter"),
    "WSL / Hyper-V virtual adapter excluded from automatic WOL selection");
Assert(WolMetadata.LooksVirtualAdapter("Ethernet 2", "VMware Virtual Ethernet Adapter"),
    "VMware virtual adapter excluded from automatic WOL selection");
Assert(!WolMetadata.LooksVirtualAdapter("Ethernet", "Intel(R) Ethernet Controller"),
    "physical Ethernet candidate retained");
Assert(BootSession.IsSameBoot(1000, 1119), "boot estimate within tolerance preserved");
Assert(!BootSession.IsSameBoot(1000, 1400), "genuine kernel restart changes boot ID");

var temp = Path.Combine(Path.GetTempPath(), "computerhost-agent-tests-" + Guid.NewGuid().ToString("N"));
try
{
    var cfg = new AgentOptions { StateDirectory = temp };
    if (OperatingSystem.IsWindows())
    {
        bool rejected = false;
        try { _ = new PersistentIdentity(cfg); } catch (InvalidDataException) { rejected = true; }
        Assert(rejected && !Directory.Exists(temp), "missing Windows state is not created by the agent");
        using var current = WindowsIdentity.GetCurrent();
        var owner = current.User!;
        var acl = new DirectorySecurity();
        acl.SetOwner(owner);
        acl.SetAccessRuleProtection(true, false);
        acl.AddAccessRule(new FileSystemAccessRule(owner, FileSystemRights.FullControl,
            InheritanceFlags.ContainerInherit | InheritanceFlags.ObjectInherit, PropagationFlags.None,
            AccessControlType.Allow));
        new DirectoryInfo(temp).Create(acl);
    }
    var id1 = new PersistentIdentity(cfg);
    Assert(!new PowerConfiguration(cfg, id1).Enabled, "monitoring mode remains default");
    var powerCfg = new AgentOptions { StateDirectory = temp, EnablePowerControl = true };
    Assert(!new PowerConfiguration(powerCfg, id1).Enabled, "missing token disables power without startup exception");
    var keyPath = Path.Combine(temp, "control-token");
    File.WriteAllText(keyPath, "invalid");
    if (OperatingSystem.IsWindows())
    {
        using var current = WindowsIdentity.GetCurrent();
        var owner = current.User!;
        var privateAcl = new FileSecurity();
        privateAcl.SetOwner(owner);
        privateAcl.SetAccessRuleProtection(true, false);
        privateAcl.AddAccessRule(new FileSystemAccessRule(owner, FileSystemRights.FullControl, AccessControlType.Allow));
        new FileInfo(keyPath).SetAccessControl(privateAcl);
    }
    Assert(!new PowerConfiguration(powerCfg, id1).Enabled, "malformed token disables power");
    Assert(File.ReadAllText(keyPath) == "invalid", "invalid token is not replaced");
    File.WriteAllText(keyPath, new string('a', 257));
    Assert(!new PowerConfiguration(powerCfg, id1).Enabled, "oversized token disables power");
    File.WriteAllText(keyPath, key);
    using (var lockedToken = new FileStream(keyPath, FileMode.Open, FileAccess.ReadWrite, FileShare.None))
        Assert(!new PowerConfiguration(powerCfg, id1).Enabled, "unreadable token disables power");
    if (OperatingSystem.IsWindows())
    {
        using var current = WindowsIdentity.GetCurrent();
        var owner = current.User!;
        var keyAcl = new FileSecurity();
        keyAcl.SetOwner(owner);
        keyAcl.SetAccessRuleProtection(true, false);
        keyAcl.AddAccessRule(new FileSystemAccessRule(owner, FileSystemRights.FullControl, AccessControlType.Allow));
        keyAcl.AddAccessRule(new FileSystemAccessRule(new SecurityIdentifier(WellKnownSidType.WorldSid, null),
            FileSystemRights.Read, AccessControlType.Allow));
        File.WriteAllText(keyPath, key);
        new FileInfo(keyPath).SetAccessControl(keyAcl);
        Assert(!new PowerConfiguration(powerCfg, id1).Enabled, "unexpected token allow ACE disables power");
        Assert(File.ReadAllText(keyPath) == key, "unsafe token is not replaced");
        var directory = new DirectoryInfo(temp);
        var unsafeAcl = directory.GetAccessControl();
        var original = AccessRules(unsafeAcl);
        var directoryRule = new FileSystemAccessRule(new SecurityIdentifier(WellKnownSidType.WorldSid, null),
            FileSystemRights.Read, AccessControlType.Allow);
        unsafeAcl.AddAccessRule(directoryRule);
        directory.SetAccessControl(unsafeAcl);
        try
        {
            bool rejected = false;
            try { _ = new PersistentIdentity(cfg); } catch (InvalidDataException) { rejected = true; }
            Assert(rejected, "unexpected state directory allow ACE refuses identity startup");
        }
        finally
        {
            // SetAccessControl persists modified sections only. Remove the
            // injected rule explicitly, then check the on-disk DACL.
            unsafeAcl.RemoveAccessRuleSpecific(directoryRule);
            directory.SetAccessControl(unsafeAcl);
            AssertRestoredRules(original, AccessRules(directory.GetAccessControl()),
                "test restored original state directory DACL");
        }

        var identityFile = new FileInfo(Path.Combine(temp, "installation-id"));
        var unsafeIdentityAcl = identityFile.GetAccessControl();
        var identityAcl = AccessRules(unsafeIdentityAcl);
        var identityRule = new FileSystemAccessRule(new SecurityIdentifier(WellKnownSidType.WorldSid, null),
            FileSystemRights.Write, AccessControlType.Allow);
        unsafeIdentityAcl.AddAccessRule(identityRule);
        identityFile.SetAccessControl(unsafeIdentityAcl);
        try
        {
            bool rejected = false;
            try { _ = new PersistentIdentity(cfg); } catch (InvalidDataException) { rejected = true; }
            Assert(rejected, "unsafe persistent identity is refused, not replaced");
        }
        finally
        {
            unsafeIdentityAcl.RemoveAccessRuleSpecific(identityRule);
            identityFile.SetAccessControl(unsafeIdentityAcl);
            AssertRestoredRules(identityAcl, AccessRules(identityFile.GetAccessControl()),
                "test restored original identity file DACL");
        }
        Assert(new PersistentIdentity(cfg).Id == id1.Id, "restored state remains usable with original identity");
    }
    File.Delete(keyPath);
    Directory.CreateDirectory(keyPath);
    Assert(!new PowerConfiguration(powerCfg, id1).Enabled, "directory in place of token disables power");
    Directory.Delete(keyPath);
    var id2 = new PersistentIdentity(cfg);
    Assert(id1.Id == id2.Id && Guid.TryParse(id1.Id, out _), "persistent identity survives process reinitialization");
    Assert(!Directory.EnumerateFiles(temp, "installation-id.*.tmp").Any(), "atomic identity leaves no temporary file after success");
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


// Dispatcher tests inject a harmless delegate; CI must never execute a real
// shutdown, reboot or suspend operation.
var powerCalls = new List<string>();
var immediateDispatcher = new PowerDispatcher(
    NullLogger<PowerDispatcher>.Instance,
    action => powerCalls.Add(action),
    _ => Task.CompletedTask);
Assert(immediateDispatcher.TrySchedule("shutdown") == PowerDispatchResult.Accepted,
    "shutdown is accepted only after the native operation delegate succeeds");
Assert(immediateDispatcher.TrySchedule("reboot") == PowerDispatchResult.Accepted,
    "reboot is accepted only after the native operation delegate succeeds");
Assert(powerCalls.SequenceEqual(new[] { "shutdown", "reboot" }),
    "shutdown and reboot delegates run synchronously before HTTP acceptance");

var alreadyShuttingDown = new PowerDispatcher(
    NullLogger<PowerDispatcher>.Instance,
    _ => throw new Win32Exception(1115),
    _ => Task.CompletedTask);
Assert(alreadyShuttingDown.TrySchedule("shutdown") == PowerDispatchResult.ShutdownInProgress,
    "ERROR_SHUTDOWN_IN_PROGRESS maps to a conflict result");

var nativeFailure = new PowerDispatcher(
    NullLogger<PowerDispatcher>.Instance,
    _ => throw new Win32Exception(5),
    _ => Task.CompletedTask);
Assert(nativeFailure.TrySchedule("reboot") == PowerDispatchResult.Failed,
    "other native power failures are not acknowledged");

var suspendGate = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
var delayRequested = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
var suspendExecuted = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
TimeSpan? suspendDelay = null;
var suspendDispatcher = new PowerDispatcher(
    NullLogger<PowerDispatcher>.Instance,
    action => { if (action == "suspend") suspendExecuted.TrySetResult(true); },
    delay =>
    {
        suspendDelay = delay;
        delayRequested.TrySetResult(true);
        return suspendGate.Task;
    });
Assert(suspendDispatcher.TrySchedule("suspend") == PowerDispatchResult.Accepted,
    "suspend retains asynchronous scheduling so the HTTP response can leave first");
await delayRequested.Task.WaitAsync(TimeSpan.FromSeconds(5));
Assert(suspendDelay == TimeSpan.FromSeconds(3), "suspend retains the three-second response grace period");
Assert(suspendDispatcher.TrySchedule("reboot") == PowerDispatchResult.Busy,
    "only one delayed power operation can be in flight");
suspendGate.SetResult(true);
await suspendExecuted.Task.WaitAsync(TimeSpan.FromSeconds(5));

await MdnsRetryTests.Run();
Console.WriteLine("All Windows Host Agent contract tests passed.");
