namespace BlogApp.Core.Domain.Enums;

/// <summary>
/// Outbox kaydının yayın yaşam döngüsü (plan satır 295-303):
/// Pending → (lease ile Claim) → confirm sonrası Published.
/// Confirm timeout/bağlantı hatasında kayıt beklemede kalır (Claimed, lease bitince
/// yeniden alınabilir); üst sınırı aşan denemeler DeadLettered olur.
/// </summary>
public enum AgentOutboxStatus
{
    /// <summary>Yayın bekliyor.</summary>
    Pending = 0,

    /// <summary>Bir publisher instance'ı lease ile aldı; confirm bekleniyor veya deneme sürüyor.</summary>
    Claimed = 1,

    /// <summary>Publisher confirm aldı; kayıt tamamlandı.</summary>
    Published = 2,

    /// <summary>Deneme üst sınırını aştı; operatör müdahalesi bekler (ölçümle raporlanır).</summary>
    DeadLettered = 3
}
