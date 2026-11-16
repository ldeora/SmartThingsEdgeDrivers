using System.Security.Cryptography;
using System.Text;

namespace ComputerHost.WindowsAgent;

/// <summary>V2 HMAC challenge compatible with the Linux agent and SmartThings Lua driver.
/// A nonce is single-use, random, expires after 30 seconds and is never logged.</summary>
public sealed class PowerAuthentication
{
    private sealed record Pending(DateTimeOffset Issued, string Remote);
    private readonly Dictionary<string, Pending> _pending = new(StringComparer.Ordinal);
    private readonly Dictionary<string, Queue<DateTimeOffset>> _rates = new(StringComparer.Ordinal);
    private readonly object _gate = new();
    private readonly byte[] _secret;
    private readonly TimeProvider _clock;
    public const int NonceLifetimeSeconds = 30;
    public const int MaxPending = 128;
    public const int MaxChallengesPerMinute = 20;

    public PowerAuthentication(string hexSecret, TimeProvider? clock = null)
    {
        if (hexSecret.Length != 64 || !hexSecret.All(Uri.IsHexDigit))
            throw new InvalidDataException("Power control requires exactly 64 hexadecimal key characters");
        _secret = Convert.FromHexString(hexSecret);
        _clock = clock ?? TimeProvider.System;
    }

    public string? Issue(string remote)
    {
        lock (_gate)
        {
            var now = _clock.GetUtcNow();
            foreach (var nonce in _pending.Where(p => now - p.Value.Issued > TimeSpan.FromSeconds(NonceLifetimeSeconds))
                         .Select(p => p.Key).ToList()) _pending.Remove(nonce);
            // Keep per-client tracking bounded; a malicious host must not consume unbounded RAM.
            foreach (var idle in _rates.Where(x => x.Value.Count == 0 ||
                         now - x.Value.Last() > TimeSpan.FromMinutes(1)).Select(x => x.Key).ToList())
                _rates.Remove(idle);
            if (!_rates.TryGetValue(remote, out var queue))
            {
                if (_rates.Count >= MaxPending) return null;
                _rates[remote] = queue = new Queue<DateTimeOffset>();
            }
            while (queue.Count > 0 && now - queue.Peek() > TimeSpan.FromMinutes(1)) queue.Dequeue();
            if (queue.Count >= MaxChallengesPerMinute || _pending.Count >= MaxPending) return null;
            queue.Enqueue(now);
            var nonceString = Convert.ToHexString(RandomNumberGenerator.GetBytes(24)).ToLowerInvariant();
            _pending.Add(nonceString, new Pending(now, remote));
            return nonceString;
        }
    }

    public string Sign(string action, string nonce)
    {
        var message = Encoding.ASCII.GetBytes($"POST\n/v2/power/{action}\n{nonce}\n");
        return Convert.ToHexString(HMACSHA256.HashData(_secret, message)).ToLowerInvariant();
    }

    public bool Authenticate(string action, string nonce, string providedSignature, string remote)
    {
        if (!AgentContract.SupportedPowerActions.Contains(action) || nonce.Length != 48 ||
            providedSignature.Length != 64 || !nonce.All(Uri.IsHexDigit) ||
            !providedSignature.All(Uri.IsHexDigit)) return false;
        var expected = Convert.FromHexString(Sign(action, nonce));
        var received = Convert.FromHexString(providedSignature);
        if (!CryptographicOperations.FixedTimeEquals(expected, received)) return false;
        lock (_gate)
        {
            if (!_pending.TryGetValue(nonce, out var pending) || pending.Remote != remote) return false;
            _pending.Remove(nonce); // Consume once, including on expired attempts.
            return _clock.GetUtcNow() - pending.Issued <= TimeSpan.FromSeconds(NonceLifetimeSeconds);
        }
    }
}

/// <summary>Fail closed if a configured key is absent or malformed; don't silently regenerate it.</summary>
public sealed class PowerConfiguration
{
    public bool Enabled { get; }
    public PowerAuthentication? Authentication { get; }
    public PowerConfiguration(AgentOptions options, PersistentIdentity identity)
    {
        if (!options.EnablePowerControl) return;
        var keyPath = Path.Combine(identity.StateDirectory, "control-token");
        if (!File.Exists(keyPath)) throw new InvalidOperationException("Power is enabled but control-token is absent");
        Authentication = new PowerAuthentication(File.ReadAllText(keyPath).Trim());
        Enabled = true;
    }
}
