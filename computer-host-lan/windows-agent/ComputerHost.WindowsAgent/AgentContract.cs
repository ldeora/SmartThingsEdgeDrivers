namespace ComputerHost.WindowsAgent;

/// <summary>The wire contract is shared with the shared Linux protocol-v2 agent.</summary>
public static class AgentContract
{
    public const string Protocol = "computer-host-agent";
    public const int ApiVersion = 2;
    public const string Platform = "windows";
    public const string AgentVersion = "0.2.6-rc.1";
    public const string ServiceType = "_computerhost._tcp.local";
    public const int DefaultPort = 8765;

    public static readonly string[] MonitoringFeatures = ["health", "metrics", "wol-metadata"];
    public static readonly string[] SupportedPowerActions = ["reboot", "shutdown", "suspend"];

    public static object Envelope(string installationId) => new
    {
        protocol = Protocol, api_version = ApiVersion, platform = Platform,
        id = installationId
    };
}
