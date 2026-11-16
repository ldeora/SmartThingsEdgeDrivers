using System.Net.NetworkInformation;
using System.Net.Sockets;

namespace ComputerHost.WindowsAgent;

/// <summary>Reports a candidate wired NIC only. NOT a claim that Windows or firmware
/// will wake from S4/S5 or even S3. Users must verify physical wake themselves.</summary>
public sealed class WolMetadata(AgentOptions options)
{
    public string? Mac { get; }
    public string? Broadcast { get; }
    public string? InterfaceId { get; }
    public WolMetadata() : this(new AgentOptions()) { }
    public WolMetadata(AgentOptions options)
    {
        try
        {
            var nic = NetworkInterface.GetAllNetworkInterfaces()
                .Where(x => x.NetworkInterfaceType == NetworkInterfaceType.Ethernet &&
                    x.OperationalStatus == OperationalStatus.Up &&
                    (string.IsNullOrEmpty(options.WolInterfaceId) ||
                     string.Equals(x.Id, options.WolInterfaceId, StringComparison.OrdinalIgnoreCase)))
                .Where(x => x.GetPhysicalAddress().GetAddressBytes().Length == 6)
                .Select(x => new { Nic = x, V4 = x.GetIPProperties().UnicastAddresses
                    .FirstOrDefault(a => a.Address.AddressFamily == AddressFamily.InterNetwork && a.IPv4Mask != null) })
                .Where(x => x.V4 != null)
                .OrderByDescending(x => x.Nic.Speed)
                .FirstOrDefault();
            if (nic is null) return;
            var mac = nic.Nic.GetPhysicalAddress().GetAddressBytes();
            if (mac.All(b => b == 0)) return;
            var ip = nic.V4!.Address.GetAddressBytes();
            var mask = nic.V4.IPv4Mask.GetAddressBytes();
            if (ip.Length != 4 || mask.Length != 4) return;
            Mac = string.Join(":", mac.Select(b => b.ToString("x2")));
            Broadcast = string.Join(".", ip.Zip(mask, (a, b) => (byte)(a | (byte)~b)));
            InterfaceId = nic.Nic.Id;
        }
        catch (NetworkInformationException) { /* No suitable NIC: omit unverified metadata. */ }
        catch (PlatformNotSupportedException) { }
    }
}
