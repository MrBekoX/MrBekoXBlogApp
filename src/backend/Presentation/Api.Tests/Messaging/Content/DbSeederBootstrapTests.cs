using BlogApp.Core.Application.Common.Options;
using BlogApp.Core.Domain.Enums;
using BlogApp.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging.Abstractions;
using Microsoft.Extensions.Options;
using Xunit;

namespace BlogApp.Presentation.Api.Tests.Messaging.Content;

[Collection("agent-content-sync-b8")]
public sealed class DbSeederBootstrapTests(ContentSyncDatabaseFixture fixture) : IAsyncLifetime
{
    public Task InitializeAsync() => fixture.ResetAsync();
    public Task DisposeAsync() => Task.CompletedTask;

    private AppDbContext CreateContext() => new(new DbContextOptionsBuilder<AppDbContext>()
        .UseNpgsql(fixture.TestConnectionString, options => options.EnableRetryOnFailure(1))
        .Options);

    private static AdminUserSettings Settings(string identity = "initial-admin") => new()
    {
        Email = identity + "@example.invalid",
        UserName = identity,
        Password = "Local-Bootstrap-Test-Password-Only-24!",
        FirstName = "Initial",
    };

    private static DbSeeder Seeder(AppDbContext context, AdminUserSettings settings) =>
        new(context, Options.Create(settings), NullLogger<DbSeeder>.Instance);

    [Fact]
    public async Task EmptyDatabase_CreatesConfiguredAdministrator()
    {
        var settings = Settings();
        await using var context = CreateContext();
        await Seeder(context, settings).SeedAsync();

        var administrator = await context.Users.AsNoTracking().SingleAsync();
        Assert.Equal(settings.Email, administrator.Email);
        Assert.Equal(settings.UserName, administrator.UserName);
        Assert.Equal(UserRole.Admin, administrator.Role);
        Assert.True(administrator.IsActive);
        Assert.True(BCrypt.Net.BCrypt.Verify(settings.Password, administrator.PasswordHash));
    }

    [Fact]
    public async Task RestartWithChangedConfiguration_PreservesExistingCredentialsAndIdentity()
    {
        await using (var create = CreateContext())
        {
            await Seeder(create, Settings()).SeedAsync();
        }
        await using var verify = CreateContext();
        var original = await verify.Users.AsNoTracking().SingleAsync();

        await using (var restart = CreateContext())
        {
            var changed = Settings("different-admin");
            changed.Password = "Different-Local-Bootstrap-Password-Only-24!";
            await Seeder(restart, changed).SeedAsync();
        }

        var preserved = await verify.Users.AsNoTracking().SingleAsync();
        Assert.Equal(original.Id, preserved.Id);
        Assert.Equal(original.PasswordHash, preserved.PasswordHash);
        Assert.Equal(original.Email, preserved.Email);
        Assert.Equal(original.UserName, preserved.UserName);
        Assert.Equal(original.FirstName, preserved.FirstName);
        Assert.Equal(UserRole.Admin, preserved.Role);
    }

    [Fact]
    public async Task ExistingReaderIdentity_IsNeverPromoted()
    {
        var reader = await fixture.SeedUserAsync("existing-reader");
        var settings = Settings();
        settings.Email = reader.Email;
        await using var context = CreateContext();

        await Assert.ThrowsAsync<InvalidOperationException>(() => Seeder(context, settings).SeedAsync());

        var preserved = await context.Users.AsNoTracking().SingleAsync();
        Assert.Equal(UserRole.Reader, preserved.Role);
        Assert.Equal(reader.PasswordHash, preserved.PasswordHash);
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task InactiveOrDeletedAdministrator_IsNotReactivated(bool deleted)
    {
        await using (var create = CreateContext())
        {
            await Seeder(create, Settings()).SeedAsync();
            var administrator = await create.Users.SingleAsync();
            administrator.IsDeleted = deleted;
            administrator.IsActive = deleted;
            await create.SaveChangesAsync();
        }
        await using var context = CreateContext();

        await Assert.ThrowsAsync<InvalidOperationException>(() => Seeder(context, Settings("replacement")).SeedAsync());

        var preserved = await context.Users.IgnoreQueryFilters().AsNoTracking().SingleAsync();
        Assert.Equal(deleted, preserved.IsDeleted);
        Assert.Equal(deleted, preserved.IsActive);
    }

    [Fact]
    public async Task MissingCredentials_FailsWithoutCreatingAccounts()
    {
        await using var context = CreateContext();
        await Assert.ThrowsAsync<InvalidOperationException>(() => Seeder(context, new AdminUserSettings()).SeedAsync());
        Assert.False(await context.Users.IgnoreQueryFilters().AnyAsync());
    }

    [Fact]
    public async Task TransientInsertFailure_RetryCreatesOnlyOneAdministrator()
    {
        await using var setup = fixture.CreateContext();
        await setup.Database.ExecuteSqlRawAsync("""
            CREATE SEQUENCE bootstrap_retry_gate;
            CREATE FUNCTION reject_first_admin_insert() RETURNS trigger LANGUAGE plpgsql AS $bootstrap_retry$
            BEGIN
                IF nextval('bootstrap_retry_gate') = 1 THEN
                    RAISE EXCEPTION 'retry bootstrap integration check' USING ERRCODE = '40001';
                END IF;
                RETURN NEW;
            END $bootstrap_retry$;
            CREATE TRIGGER bootstrap_retry_gate BEFORE INSERT ON users
                FOR EACH ROW EXECUTE FUNCTION reject_first_admin_insert();
            """);
        try
        {
            await using var retry = CreateContext();
            await Seeder(retry, Settings()).SeedAsync();
            await using var verify = fixture.CreateContext();
            Assert.Equal(1, await verify.Users.CountAsync(user => user.Role == UserRole.Admin));
        }
        finally
        {
            await setup.Database.ExecuteSqlRawAsync("""
                DROP TRIGGER IF EXISTS bootstrap_retry_gate ON users;
                DROP FUNCTION IF EXISTS reject_first_admin_insert();
                DROP SEQUENCE IF EXISTS bootstrap_retry_gate;
                """);
        }
    }

    [Fact]
    public async Task ConcurrentBootstrapWithDifferentIdentities_CreatesOnlyOneAdministrator()
    {
        await using var first = CreateContext();
        await using var second = CreateContext();
        await Task.WhenAll(
            Seeder(first, Settings("first-initial-admin")).SeedAsync(),
            Seeder(second, Settings("second-initial-admin")).SeedAsync());

        await using var verify = CreateContext();
        Assert.Equal(1, await verify.Users.CountAsync(user => user.Role == UserRole.Admin));
    }
}
