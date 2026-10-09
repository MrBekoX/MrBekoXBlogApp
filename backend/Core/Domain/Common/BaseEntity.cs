namespace BlogApp.Core.Domain.Common;

/// <summary>
/// Tüm entity'ler için temel sınıf
/// </summary>
public abstract class BaseEntity
{
    public Guid Id { get; set; }
}
