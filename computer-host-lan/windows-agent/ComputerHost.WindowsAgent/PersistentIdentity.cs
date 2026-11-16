using System.Text;

namespace ComputerHost.WindowsAgent;

/// <summary>
/// Never regenerate on read errors: changing the UUID creates a second SmartThings device.
/// The installer must grant LocalService exclusive write access to the state directory.
/// </summary>
public sealed class PersistentIdentity
{
    public string Id { get; }
    public string StateDirectory { get; }

    public PersistentIdentity(AgentOptions options)
    {
        StateDirectory = options.StateDirectory ??
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData), "ComputerHostAgent");
        Directory.CreateDirectory(StateDirectory);
        var path = Path.Combine(StateDirectory, "installation-id");
        try
        {
            using var writer = new FileStream(path, FileMode.CreateNew, FileAccess.Write, FileShare.None);
            var bytes = Encoding.ASCII.GetBytes(Guid.NewGuid().ToString("D") + "\n");
            writer.Write(bytes);
            writer.Flush(true);
        }
        catch (IOException) when (File.Exists(path))
        {
            // The identity already exists, e.g. after a service restart or upgrade.
        }
        var raw = File.ReadAllText(path, Encoding.ASCII).Trim();
        if (!Guid.TryParseExact(raw, "D", out var guid) ||
            !string.Equals(guid.ToString("D"), raw, StringComparison.Ordinal))
        {
            throw new InvalidDataException("Persistent computer host installation UUID is invalid; refusing to create a new identity.");
        }
        Id = raw;
    }
}
