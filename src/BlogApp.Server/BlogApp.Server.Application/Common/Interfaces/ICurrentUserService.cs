namespace BlogApp.Server.Application.Common.Interfaces;

/// <summary>
/// Mevcut kullanıcı bilgisi servisi
/// </summary>
public interface ICurrentUserService
{
    Guid? UserId { get; }
    string? UserName { get; }
    string? Email { get; }
    bool IsAuthenticated { get; }
    bool IsInRole(string role);
}
