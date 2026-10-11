using BlogApp.Core.Domain.Entities;

namespace BlogApp.Core.Application.Common.Interfaces.Messaging;

/// <summary>
/// Outbox kaydını ortam transaction'ının içine ekler (B0 §4 Interfaces/Messaging soyutlaması).
/// Uygulama (Infrastructure) kaydı AppDbContext.OutboxMessages setine ekler; kayıt,
/// iş verisiyle AYNI DB transaction'ında commit edilir (plan satır 292). Yayın sorumluluğu
/// ayrı relay hosted service'indir; bu arayüz broker'a dokunmaz.
/// </summary>
public interface IOutboxWriter
{
    Task AddAsync(OutboxMessage message, CancellationToken cancellationToken = default);
}
