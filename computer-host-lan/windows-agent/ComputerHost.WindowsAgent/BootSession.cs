using System.Text.Json;

namespace ComputerHost.WindowsAgent;

/// <summary>
/// Approximate a Windows kernel boot session using GetTickCount64 rather than an agent start timestamp.
/// Persist GUID across service restarts and sleep/resume; rotate after an observed kernel restart.
/// Clock adjustment and Fast Startup can affect this heuristic, so Windows hardware validation is required.
/// </summary>
public sealed class BootSession
{
    private sealed record StoredBoot(string BootId, long EstimatedBootUnixSeconds);
    public string BootId { get; }

    public BootSession(PersistentIdentity identity, ulong uptimeMs)
    {
        var path = Path.Combine(identity.StateDirectory, "boot-session.json");
        var estimate = DateTimeOffset.UtcNow.ToUnixTimeSeconds() - (long)(uptimeMs / 1000);
        StoredBoot? existing = null;
        if (File.Exists(path))
        {
            try { existing = JsonSerializer.Deserialize<StoredBoot>(File.ReadAllText(path)); }
            catch (JsonException) { /* Rebuild a non-secret derived cache on corruption. */ }
        }
        if (existing is not null && IsSameBoot(existing.EstimatedBootUnixSeconds, estimate) &&
            Guid.TryParseExact(existing.BootId, "D", out _))
        {
            BootId = existing.BootId;
            return;
        }
        BootId = Guid.NewGuid().ToString("D");
        var json = JsonSerializer.Serialize(new StoredBoot(BootId, estimate));
        var temp = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
        File.WriteAllText(temp, json);
        File.Move(temp, path, overwrite: true);
    }

    // A two-minute tolerance allows scheduling and time measurement uncertainty;
    // very large clock corrections remain a known potential false-positive.
    public static bool IsSameBoot(long previousEstimatedBoot, long currentEstimatedBoot) =>
        Math.Abs(previousEstimatedBoot - currentEstimatedBoot) <= 120;
}
