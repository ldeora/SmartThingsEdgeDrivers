using System.Runtime.Versioning;
using System.Security.AccessControl;
using System.Security.Principal;
using Microsoft.Extensions.Hosting.WindowsServices;

namespace ComputerHost.WindowsAgent;

/// <summary>Validate the installer-owned Windows state boundary before use.
/// Never repair ACLs, create a missing directory or follow a state reparse point.
/// The service is trusted; this is not protection against administrators
/// changing files concurrently or after startup.</summary>
[SupportedOSPlatform("windows")]
internal sealed class StateProtection
{
    private const string Administrators = "S-1-5-32-544";
    private const string System = "S-1-5-18";
    private const string LocalService = "S-1-5-19";
    // Windows service SID for ComputerHostAgent (sc.exe showsid ComputerHostAgent).
    private const string Service = "S-1-5-80-3087533459-2037897677-1353449284-3397642928-3366244619";
    private readonly string _directory;
    private readonly string? _consoleOwner;

    public StateProtection(string directory, bool explicitDirectory)
    {
        _directory = directory;
        using var identity = WindowsIdentity.GetCurrent();
        var user = identity.User ?? throw UnsafeState();
        var principal = new WindowsPrincipal(identity);
        bool service = WindowsServiceHelpers.IsWindowsService() ||
            user.Value == LocalService || principal.IsInRole(new SecurityIdentifier(Service));
        if (service)
        {
            if (user.Value != LocalService || !principal.IsInRole(new SecurityIdentifier(Service)))
                throw UnsafeState();
        }
        else if (explicitDirectory)
        {
            // Non-service development console runs may use a separately
            // provisioned private directory owned by the invoking user.
            // No configuration flag can select this policy for the service.
            _consoleOwner = user.Value;
        }
        ValidateDirectory();
    }

    private static InvalidDataException UnsafeState() =>
        new("Windows agent state is missing or unsafe; use the installer to inspect and repair it. Preserve existing identity and credentials.");

    private bool IsAdmin(string sid) =>
        sid == Administrators || sid == System || sid == _consoleOwner;

    private static FileAttributes? AttributesIfPresent(string path)
    {
        try { return File.GetAttributes(path); }
        catch (FileNotFoundException) { return null; }
        catch (DirectoryNotFoundException) { return null; }
    }

    private void CheckSecurity(FileSystemSecurity security, bool agentFile, bool token)
    {
        var owner = security.GetOwner(typeof(SecurityIdentifier))?.Value;
        if (owner is null || !(IsAdmin(owner) || (agentFile && (owner == LocalService || owner == Service))))
            throw UnsafeState();
        if (!agentFile && !security.AreAccessRulesProtected)
            throw UnsafeState();
        // Inspect the raw DACL, including unsupported ACEs and null DACLs,
        // rather than silently ignoring entries outside GetAccessRules().
        var descriptor = new RawSecurityDescriptor(security.GetSecurityDescriptorBinaryForm(), 0);
        var dacl = descriptor.DiscretionaryAcl;
        if (dacl is null)
            throw UnsafeState();
        foreach (GenericAce entry in dacl)
        {
            if (entry is not CommonAce ace || ace.IsCallback ||
                ace.AceQualifier is not (AceQualifier.AccessAllowed or AceQualifier.AccessDenied))
                throw UnsafeState();
            if (ace.AceQualifier == AceQualifier.AccessDenied)
                continue;
            string sid = ace.SecurityIdentifier.Value;
            if (!IsAdmin(sid) && sid != Service)
                throw UnsafeState();
            // The exact service SID may read the token, but no broader
            // explicit write/delete/ACL permissions are allowed on the file.
            if (token && sid == Service &&
                (ace.AccessMask & ~(int)(FileSystemRights.Read | FileSystemRights.Synchronize)) != 0)
                throw UnsafeState();
        }
    }

    public void ValidateDirectory()
    {
        var attributes = AttributesIfPresent(_directory);
        if (attributes is null || (attributes.Value & FileAttributes.Directory) == 0 ||
            (attributes.Value & FileAttributes.ReparsePoint) != 0)
            throw UnsafeState();
        CheckSecurity(new DirectoryInfo(_directory).GetAccessControl(
            AccessControlSections.Owner | AccessControlSections.Access), agentFile: false, token: false);
    }

    public bool ValidateFileIfPresent(string name, bool token = false)
    {
        ValidateDirectory();
        var path = Path.Combine(_directory, name);
        var attributes = AttributesIfPresent(path);
        if (attributes is null)
            return false;
        if ((attributes.Value & (FileAttributes.Directory | FileAttributes.ReparsePoint)) != 0)
            throw UnsafeState();
        CheckSecurity(new FileInfo(path).GetAccessControl(
            AccessControlSections.Owner | AccessControlSections.Access), agentFile: !token, token: token);
        return true;
    }
}
