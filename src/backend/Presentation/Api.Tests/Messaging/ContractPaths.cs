namespace BlogApp.Presentation.Api.Tests.Messaging;

/// <summary>Tek kaynak sözleşme dosyalarına (src/contracts/agent) repo kökünden ulaşım;
/// test çıkış dizininden yukarı doğru arama yapar.</summary>
internal static class ContractPaths
{
    internal static string ContractRoot { get; } = FindContractRoot();

    internal static string V1Directory => Path.Combine(ContractRoot, "v1");

    internal static string V2Directory => Path.Combine(ContractRoot, "v2");

    /// <summary>v1 ortak fixture'ları (manifest.json, valid/, invalid/).</summary>
    internal static string FixturesDirectory => Path.Combine(ContractRoot, "fixtures");

    /// <summary>v2 ortak fixture'ları (fixtures/v2/manifest.json, valid/, invalid/).</summary>
    internal static string V2FixturesDirectory => Path.Combine(FixturesDirectory, "v2");

    internal static string VersionDirectory(int version) => version switch
    {
        1 => V1Directory,
        2 => V2Directory,
        _ => throw new ArgumentOutOfRangeException(nameof(version), version, "sözleşme sürümü dizini yok"),
    };

    internal static string FixturesDirectoryFor(int version) => version switch
    {
        1 => FixturesDirectory,
        2 => V2FixturesDirectory,
        _ => throw new ArgumentOutOfRangeException(nameof(version), version, "fixture dizini yok"),
    };

    private static string FindContractRoot()
    {
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir is not null)
        {
            var candidate = Path.Combine(dir.FullName, "src", "contracts", "agent");
            if (Directory.Exists(candidate))
            {
                return candidate;
            }

            dir = dir.Parent;
        }

        throw new InvalidOperationException("src/contracts/agent dizini repo kökünde bulunamadı");
    }
}
