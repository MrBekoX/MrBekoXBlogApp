namespace BlogApp.Core.Application.Common.Options;

/// <summary>
/// Admin user seeding configuration settings
/// </summary>
public sealed class AdminUserSettings
{
    public const string SectionName = "AdminUser";

    public string? Email { get; set; }
    public string? UserName { get; set; }
    public string? Password { get; set; }
    public string FirstName { get; set; } = "Admin";
}

