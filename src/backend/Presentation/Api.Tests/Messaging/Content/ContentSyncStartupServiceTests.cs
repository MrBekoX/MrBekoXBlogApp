using BlogApp.Core.Application.Common.AuthorProfile;
using BlogApp.Core.Application.Common.Interfaces.Data;
using BlogApp.Core.Application.Common.Interfaces.Messaging;
using BlogApp.Core.Application.Common.Interfaces.Persistence;
using BlogApp.Core.Domain.Enums;
using BlogApp.Infrastructure.Messaging;
using BlogApp.Infrastructure.Persistence;
using BlogApp.Infrastructure.Persistence.Repositories;
using BlogApp.Infrastructure.Services.AuthorProfile;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Xunit;

namespace BlogApp.Presentation.Api.Tests.Messaging.Content;

[Collection("agent-content-sync-b8")]
public sealed class ContentSyncStartupServiceTests(ContentSyncDatabaseFixture fixture) : IAsyncLifetime
{
    public Task InitializeAsync() => fixture.ResetAsync();
    public Task DisposeAsync() => Task.CompletedTask;

    private ServiceProvider Provider(string? profileDirectory = null)
    {
        var configuration = new ConfigurationBuilder().AddInMemoryCollection(new Dictionary<string, string?>
        {
            ["AgentContentSync:Enabled"] = "true",
            ["AgentContentSync:BatchSize"] = "1",
            ["AgentContentSync:StartupMaxAttempts"] = "1",
            ["AgentContentSync:StartupRetryDelaySeconds"] = "0",
        }).Build();
        var services = new ServiceCollection();
        services.AddLogging();
        services.AddDbContext<AppDbContext>(options => options.UseNpgsql(fixture.TestConnectionString, npgsql => npgsql.EnableRetryOnFailure(1)));
        services.AddScoped<IApplicationDbContext>(provider => provider.GetRequiredService<AppDbContext>());
        services.AddScoped<IUnitOfWork, UnitOfWork>();
        services.AddScoped<IOutboxWriter, EfOutboxWriter>();
        services.AddSingleton<IAuthorProfileSource>(new FileAuthorProfileSource(
            profileDirectory ?? Path.Combine(AppContext.BaseDirectory, "content", "author-profile")));
        services.AddAgentContentEvents(configuration);
        return services.BuildServiceProvider(new ServiceProviderOptions { ValidateScopes = true });
    }

    private static ContentSyncStartupService Startup(ServiceProvider provider) =>
        provider.GetServices<IHostedService>().OfType<ContentSyncStartupService>().Single();

    [Fact]
    public async Task StartAsync_ReturnsOnlyAfterSnapshotAndOutboxAreCommitted()
    {
        var author = await fixture.SeedUserAsync();
        await fixture.SeedPostAsync(author.Id, "Startup Published", PostStatus.Published, contentRevision: 7);
        await fixture.SeedPostAsync(author.Id, "Startup Draft", PostStatus.Draft);
        await using var provider = Provider();

        await Startup(provider).StartAsync(CancellationToken.None);

        await using var verify = fixture.CreateContext();
        var sync = await verify.AgentContentSyncs.AsNoTracking().SingleAsync();
        Assert.Equal(AgentContentSyncStatus.Completed, sync.Status);
        Assert.Equal(1, sync.ItemCount);
        Assert.Equal(1, sync.TotalBatches);
        Assert.Equal(2, await verify.OutboxMessages.CountAsync());
        Assert.All(await verify.OutboxMessages.AsNoTracking().ToListAsync(), message =>
            Assert.Equal(AgentOutboxStatus.Pending, message.Status));
    }

    [Fact]
    public async Task Restart_WritesFreshDurableSnapshotWithoutRequiringBroker()
    {
        var author = await fixture.SeedUserAsync();
        await fixture.SeedPostAsync(author.Id, "Restart Published", PostStatus.Published, contentRevision: 2);
        await using (var first = Provider())
        {
            await Startup(first).StartAsync(CancellationToken.None);
        }
        await using (var restart = Provider())
        {
            await Startup(restart).StartAsync(CancellationToken.None);
        }

        await using var verify = fixture.CreateContext();
        Assert.Equal(2, await verify.AgentContentSyncs.CountAsync());
        Assert.Equal(4, await verify.OutboxMessages.CountAsync());
    }

    [Fact]
    public async Task MissingCanonicalProfile_RefusesStartupWithoutPartialOutbox()
    {
        var missingDirectory = Path.Combine(Path.GetTempPath(), "blogapp-missing-profile-" + Guid.NewGuid().ToString("N"));
        await using var provider = Provider(missingDirectory);

        await Assert.ThrowsAsync<InvalidOperationException>(() => Startup(provider).StartAsync(CancellationToken.None));

        await using var verify = fixture.CreateContext();
        Assert.False(await verify.AgentContentSyncs.AnyAsync());
        Assert.False(await verify.OutboxMessages.AnyAsync());
    }
}
