namespace BlogApp.Core.Application.Common.Messaging;

/// <summary>Sözleşme ihlali kategorileri; Python transport katmanındaki kategori kümesinin aynısıdır
/// ve fixtures/manifest.json "reason" değerleriyle birebir eşlenir.</summary>
public enum AgentContractErrorCategory
{
    None = 0,
    MissingField,
    UnknownVersion,
    UnknownType,
    Oversized,
    WrongType,
    BadFormat,
    ExtraField,
    ProducerMismatch
}

/// <summary>Kategorize edilmiş tek sözleşme ihlali; doğrulayıcı ilk bulduğu ihlalde durur.</summary>
public sealed record AgentContractError(AgentContractErrorCategory Category, string Field, string Message)
{
    public override string ToString() => $"{Category} ({Field}): {Message}";
}
