using System.Net;
using Microsoft.AspNetCore.Connections;

namespace ComputerHost.WindowsAgent;

/// <summary>Connection-level admission, before HTTP parsing.</summary>
internal sealed class SourceConnectionLimit
{
    // Allow a health poll, metrics poll, command and discovery request.
    internal const int MaxPerSource = 4;
    private readonly object gate = new();
    private readonly Dictionary<IPAddress, int> active = new();

    internal ConnectionDelegate Wrap(ConnectionDelegate next) => async connection =>
    {
        if (connection.RemoteEndPoint is not IPEndPoint remote)
        {
            connection.Abort();
            return;
        }
        var address = remote.Address;
        if (address.IsIPv4MappedToIPv6) address = address.MapToIPv4();
        bool admitted;
        lock (gate)
        {
            active.TryGetValue(address, out int count);
            admitted = count < MaxPerSource;
            if (admitted) active[address] = count + 1;
        }
        if (!admitted)
        {
            connection.Abort();
            return;
        }
        try { await next(connection); }
        finally
        {
            lock (gate)
            {
                int remaining = active[address] - 1;
                if (remaining == 0) active.Remove(address);
                else active[address] = remaining;
            }
        }
    };
}
