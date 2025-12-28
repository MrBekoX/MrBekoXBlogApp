namespace BlogApp.Server.Application.Common.Options;

/// <summary>
/// Admin user seeding configuration settings
/// </summary>
public sealed class AdminUserSettings
{
    public const string SectionName = "AdminUser";

    public string? Email { get; init; }
    public string? UserName { get; init; }
    public string? Password { get; init; }
    public string FirstName { get; init; } = "Admin";
}
