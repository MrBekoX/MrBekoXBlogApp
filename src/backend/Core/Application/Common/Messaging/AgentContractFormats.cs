using System.Globalization;
using System.Text.RegularExpressions;

namespace BlogApp.Core.Application.Common.Messaging;

/// <summary>
/// Sözleşme biçim kuralları: kanonik küçük harf tireli UUID, 'Z' sonekli UTC ISO 8601,
/// SHA-256 hex özeti, dil kodu ve W3C traceparent. Kaynak: src/contracts/agent/v1/common.schema.json.
/// </summary>
public static partial class AgentContractFormats
{
    public static bool IsValidUuid(string value) =>
        UuidRegex().IsMatch(value) && Guid.TryParseExact(value, "D", out _);

    public static bool IsValidUtcIso(string value)
    {
        if (!UtcIsoRegex().IsMatch(value))
        {
            return false;
        }

        // Kalıp 'Z' ile biter; RoundtripKind çözümlemesi takvim geçerliliğini ve UTC ofsetini doğrular.
        return DateTimeOffset.TryParse(value, CultureInfo.InvariantCulture, DateTimeStyles.RoundtripKind, out var parsed)
            && parsed.Offset == TimeSpan.Zero;
    }

    public static bool IsValidHashHex(string value) => HashHexRegex().IsMatch(value);

    public static bool IsValidLanguageCode(string value) => LanguageCodeRegex().IsMatch(value);

    public static bool IsValidTraceParent(string value) => TraceParentRegex().IsMatch(value);

    [GeneratedRegex("^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")]
    private static partial Regex UuidRegex();

    [GeneratedRegex("^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\\.[0-9]{1,6})?Z$")]
    private static partial Regex UtcIsoRegex();

    [GeneratedRegex("^[0-9a-f]{64}$")]
    private static partial Regex HashHexRegex();

    [GeneratedRegex("^[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})?$")]
    private static partial Regex LanguageCodeRegex();

    [GeneratedRegex("^[0-9a-f]{2}-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$")]
    private static partial Regex TraceParentRegex();
}
