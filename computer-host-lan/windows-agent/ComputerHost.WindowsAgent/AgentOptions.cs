namespace ComputerHost.WindowsAgent;

public sealed class AgentOptions
{
    public int Port { get; set; } = AgentContract.DefaultPort;
    public bool DiscoveryEnabled { get; set; } = true;
    /// <summary>0 means all interfaces. For testing, specify the physical LAN interface's Windows index.</summary>
    public uint DiscoveryInterfaceIndex { get; set; }
    public string? StateDirectory { get; set; }
    public bool EnablePowerControl { get; set; } = false;
    public string? WolInterfaceId { get; set; }
}
