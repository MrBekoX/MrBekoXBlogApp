namespace BlogApp.Server.Domain.Common;

/// <summary>
/// Tüm entity'ler için temel sınıf
/// </summary>
public abstract class BaseEntity
{
    public Guid Id { get; set; }
}
