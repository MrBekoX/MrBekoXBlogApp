using BlogApp.Core.Domain.Entities;

namespace BlogApp.Core.Application.Common.Interfaces.Messaging;

/// <summary>Makale değişim gözlemi: RecordChangeAsync çağrısından ÖNCEKI yayın durumu ve
/// içerik özeti; görünürlük geçişini ve gerçek içerik değişimini ayırt etmek için kullanılır.</summary>
public sealed record ArticleContentObservation(bool WasPublished, string? ContentHash);

/// <summary>
/// B8: makale içeriği/yayın görünürlüğü değişimini backend-atandı monoton
/// <c>BlogPost.ContentRevision</c> artışına ve makale kaydıyla AYNI transaction'a
/// yazılan ArticleContentChangedV1 outbox kaydına bağlar (plan B8: "Makale
/// değişikliğiyle içerik outbox olayını aynı transaction'da yaz").
/// Kural kümesi: taslak içerik olayla TAŞINMAZ; görünürlük kazanımı/kaybı ve
/// yayımlanmış içeriğin gerçek değişimi revision artırır; görüntülenme gibi
/// ilgisiz güncellemeler bu servise hiç uğramaz ve revision değiştirmez.
/// </summary>
public interface IAgentContentEventService
{
    /// <summary>Değişimden önceki yayın durumunu ve içerik özetini kaydeder; handler akışın
    /// başında çağrılır.</summary>
    ArticleContentObservation Observe(BlogPost post);

    /// <summary>Değişim uygulandıktan sonra (handler SaveChanges'tan önce) çağrılır:
    /// gerekiyorsa ContentRevision'ı artırır ve outbox zarfını yazar. Kayıt,
    /// handler'ın tek SaveChanges transaction'ıyla commit edilir.</summary>
    Task RecordChangeAsync(BlogPost post, ArticleContentObservation before, CancellationToken cancellationToken = default);
}
