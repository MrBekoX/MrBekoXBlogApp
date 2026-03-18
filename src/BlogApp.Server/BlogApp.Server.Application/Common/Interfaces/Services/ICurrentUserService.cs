namespace BlogApp.Server.Application.Common.Interfaces.Services;

/// <summary>
/// Mevcut kullanıcı bilgisi servisi
/// </summary>
public interface ICurrentUserService
{
    Guid? UserId { get; }
    string? UserName { get; }
    string? Email { get; }
    string? CorrelationId { get; }
    bool IsAuthenticated { get; }
    bool IsInRole(string role);
}

