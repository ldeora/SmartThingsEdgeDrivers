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
    private readonly StateProtection? _protection;

    public PersistentIdentity(AgentOptions options)
    {
        StateDirectory = options.StateDirectory ??
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData), "ComputerHostAgent");
        if (OperatingSystem.IsWindows())
            _protection = new StateProtection(StateDirectory, options.StateDirectory is not null);
        else
            Directory.CreateDirectory(StateDirectory); // Portable contract tests only; Windows executable refuses other OSes.
        var path = Path.Combine(StateDirectory, "installation-id");
        // Create into a private same-directory temporary file and atomically publish it.
        // A power loss before the move can leave an unused .tmp file, but never a
        // zero-byte installation-id. Never regenerate an existing invalid identity.
        if (!ValidateAgentFile("installation-id"))
        {
            var temporary = Path.Combine(StateDirectory, "installation-id." + Guid.NewGuid().ToString("N") + ".tmp");
            try
            {
                using (var writer = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None))
                {
                    var bytes = Encoding.ASCII.GetBytes(Guid.NewGuid().ToString("D") + "\n");
                    writer.Write(bytes);
                    writer.Flush(true);
                }
                try { File.Move(temporary, path); }
                catch (IOException) when (File.Exists(path))
                {
                    // Another instance won the identity creation race; read its identity.
                }
            }
            finally
            {
                if (File.Exists(temporary)) File.Delete(temporary);
            }
        }
        if (!ValidateAgentFile("installation-id"))
            throw new InvalidDataException("Persistent identity is missing after creation.");
        var raw = File.ReadAllText(path, Encoding.ASCII).Trim();
        if (!Guid.TryParseExact(raw, "D", out var guid) ||
            !string.Equals(guid.ToString("D"), raw, StringComparison.Ordinal))
        {
            throw new InvalidDataException("Persistent computer host installation UUID is invalid; refusing to create a new identity.");
        }
        Id = raw;
    }

    internal bool ValidateAgentFile(string name) =>
        OperatingSystem.IsWindows()
            ? _protection!.ValidateFileIfPresent(name)
            : File.Exists(Path.Combine(StateDirectory, name));

    internal bool ValidatePowerToken() =>
        OperatingSystem.IsWindows()
            ? _protection!.ValidateFileIfPresent("control-token", token: true)
            : File.Exists(Path.Combine(StateDirectory, "control-token"));
}
