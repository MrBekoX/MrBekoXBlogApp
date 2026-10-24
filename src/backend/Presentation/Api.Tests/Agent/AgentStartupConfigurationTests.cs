using BlogApp.Core.Application.Common.Options;
using BlogApp.Infrastructure;
using BlogApp.Infrastructure.Messaging;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Options;
using Xunit;

namespace BlogApp.Presentation.Api.Tests.Agent;

public sealed class AgentStartupConfigurationTests
{
    [Fact]
    public async Task DisabledContentSync_DoesNotRequireDatabaseOrProfile()
    {
        var services = new ServiceCollection();
        services.AddLogging();
        services.AddAgentContentEvents(new ConfigurationBuilder().Build());
        await using var provider = services.BuildServiceProvider();
        var startup = provider.GetServices<IHostedService>().OfType<ContentSyncStartupService>().Single();

        await startup.StartAsync(CancellationToken.None);
    }

    [Theory]
    [InlineData("AgentContentSync:BatchSize", "0")]
    [InlineData("AgentContentSync:StartupMaxAttempts", "0")]
    [InlineData("AgentContentSync:StartupRetryDelaySeconds", "-1")]
    public void InvalidStartupLimits_AreRejected(string key, string value)
    {
        var configuration = new ConfigurationBuilder().AddInMemoryCollection(new Dictionary<string, string?>
        {
            [key] = value,
        }).Build();
        var services = new ServiceCollection();
        services.AddLogging();
        services.AddAgentContentEvents(configuration);
        using var provider = services.BuildServiceProvider();

        Assert.Throws<OptionsValidationException>(() => provider.GetRequiredService<IOptions<AgentContentSyncSettings>>().Value);
    }

    [Fact]
    public void AdministratorSettings_AcceptNestedAndLegacyFlatConfiguration()
    {
        var configuration = new ConfigurationBuilder().AddInMemoryCollection(new Dictionary<string, string?>
        {
            ["ConnectionStrings:DefaultConnection"] = "Host=localhost;Database=not-opened;Username=not-used",
            ["AdminUser:Email"] = "nested@example.invalid",
            ["AdminUser:UserName"] = "nested",
            ["AdminUser:Password"] = "Nested-Configuration-Test-Only!",
            ["ADMIN_EMAIL"] = "legacy@example.invalid",
            ["ADMIN_USERNAME"] = "legacy",
            ["ADMIN_PASSWORD"] = "Legacy-Configuration-Test-Only!",
        }).Build();
        var services = new ServiceCollection();
        services.AddLogging();
        services.AddInfrastructureServices(configuration);
        using var provider = services.BuildServiceProvider();
        var settings = provider.GetRequiredService<IOptions<AdminUserSettings>>().Value;

        Assert.Equal("legacy@example.invalid", settings.Email);
        Assert.Equal("legacy", settings.UserName);
        Assert.Equal("Legacy-Configuration-Test-Only!", settings.Password);
    }
}
