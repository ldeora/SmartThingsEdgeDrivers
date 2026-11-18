// Standalone, read-only local SmartThings hub discovery for the Inno Setup wizard.
// Searches the SmartThings DNS-SD service; never guesses that a router or
// unrelated SSDP response is a SmartThings hub. No cloud credentials required.
using System.Net;
using System.Net.Sockets;
using System.Text;
using Zeroconf;

internal static class Program
{
    private const string Service = "_smartthings._tcp.local.";

    internal static string? ValidIp(string? input)
    {
        if (!IPAddress.TryParse(input, out var address) ||
            address.AddressFamily != AddressFamily.InterNetwork)
            return null;
        var bytes = address.GetAddressBytes();
        // Exclude unspecified, loopback, link-local and multicast/broadcast.
        if (bytes[0] == 0 || bytes[0] == 127 || bytes[0] == 169 && bytes[1] == 254 ||
            bytes[0] >= 224 || bytes.All(b => b == 255))
            return null;
        return address.ToString();
    }

    internal static string SafeName(string? input)
    {
        var cleaned = new string((input ?? "").Where(c =>
            c >= ' ' && c != '|' && c != '\r' && c != '\n').Take(100).ToArray()).Trim();
        return cleaned.Length == 0 ? "SmartThings Hub" : cleaned;
    }

    internal static string[] Format(IEnumerable<(string? Ip, string? Name)> discovered)
    {
        return discovered.Select(item => (Ip: ValidIp(item.Ip), Name: SafeName(item.Name)))
            .Where(item => item.Ip is not null)
            .GroupBy(item => item.Ip!, StringComparer.Ordinal)
            .Select(group => group.Key + "|" + group.First().Name)
            .OrderBy(line => line, StringComparer.Ordinal)
            .Take(32)
            .ToArray();
    }

    private static bool SelfTest()
    {
        var lines = Format(new (string?, string?)[]
        {
            ("192.168.1.20", "Hub A"),
            ("192.168.1.20", "Duplicate"),
            ("10.0.0.42", "Hub|B\r\n"),
            ("224.0.0.1", "Multicast"),
            ("169.254.1.5", "Linklocal"),
            ("127.0.0.1", "Loopback"),
            ("", "Empty")
        });
        return lines.Length == 2 && lines.Contains("192.168.1.20|Hub A") &&
               lines.Contains("10.0.0.42|HubB");
    }

    public static async Task<int> Main(string[] args)
    {
        if (args.Length == 1 && args[0] == "--self-test")
        {
            if (!SelfTest()) return 3;
            Console.WriteLine("PASS: hub candidates validated, sanitized and de-duplicated");
            return 0;
        }
        if (args.Length != 2 || args[0] != "--output" || string.IsNullOrWhiteSpace(args[1]))
        {
            Console.Error.WriteLine("Usage: ComputerHost.HubDiscovery --output <output-file>");
            return 2;
        }

        // The output file contains only IPv4/name pairs. Never emit secrets,
        // credentials, device UUIDs or complete multicast packet contents.
        var output = Path.GetFullPath(args[1]);
        try
        {
            // Validated for the historical SmartThings hub DNS-SD advertisement.
            // Hardware may not advertise, or multicast may be filtered by VLANs.
            var hosts = await ZeroconfResolver.ResolveAsync(Service, TimeSpan.FromSeconds(4),
                retries: 1, retryDelayMilliseconds: 500);
            var lines = Format(hosts.Select(host => ((string?)host.IPAddress, (string?)host.DisplayName)));
            await File.WriteAllLinesAsync(output, lines, new UTF8Encoding(false));
            Console.WriteLine("Found " + lines.Length + " SmartThings hub candidate(s).");
            return 0;
        }
        catch (Exception ex) when (ex is SocketException or TimeoutException or
                                   InvalidOperationException or System.Net.NetworkInformation.NetworkInformationException)
        {
            // A failed discovery is not a failed installation: allow manual IP.
            await File.WriteAllTextAsync(output, "", new UTF8Encoding(false));
            Console.Error.WriteLine("Local mDNS discovery unavailable: " + ex.GetType().Name);
            return 0;
        }
    }
}
