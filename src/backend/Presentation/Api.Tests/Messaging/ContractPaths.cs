namespace BlogApp.Presentation.Api.Tests.Messaging;

/// <summary>Tek kaynak sözleşme dosyalarına (src/contracts/agent) repo kökünden ulaşım;
/// test çıkış dizininden yukarı doğru arama yapar.</summary>
internal static class ContractPaths
{
    internal static string ContractRoot { get; } = FindContractRoot();

    internal static string V1Directory => Path.Combine(ContractRoot, "v1");

    internal static string FixturesDirectory => Path.Combine(ContractRoot, "fixtures");

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
