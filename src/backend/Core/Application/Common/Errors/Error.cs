namespace BlogApp.Core.Application.Common.Errors;

/// <summary>
/// Rich error descriptor produced by handlers/business rules. Carried inside <see cref="Models.Result"/>
/// instead of throwing for expected error paths. Maps to HTTP status at the API boundary
/// via <see cref="ErrorCategory"/>.
/// </summary>
/// <param name="Category">Logical error category (drives HTTP status mapping).</param>
/// <param name="Message">Human-readable message; safe to surface to client.</param>
/// <param name="FieldErrors">Optional field → messages map for validation errors.</param>
/// <param name="Code">Optional machine-readable code (e.g. "capability_unavailable"); surfaced as
/// <c>ApiResponse.code</c> so clients can branch without parsing localized messages.</param>
public sealed record Error(
    ErrorCategory Category,
    string Message,
    IReadOnlyDictionary<string, string[]>? FieldErrors = null,
    string? Code = null)
{
    /// <summary>Default code of <see cref="Unavailable"/>: a capability (feature gate, dependency,
    /// canonical source) is not ready; the request was not executed and may be retried later.</summary>
    public const string CapabilityUnavailableCode = "capability_unavailable";

    public static Error Validation(IReadOnlyDictionary<string, string[]> fieldErrors)
        => new(ErrorCategory.Validation, "Bir veya daha fazla validasyon hatasi olustu.", fieldErrors);

    public static Error Validation(string message)
        => new(ErrorCategory.Validation, message);

    public static Error NotFound(string message)
        => new(ErrorCategory.NotFound, message);

    public static Error Conflict(string message)
        => new(ErrorCategory.Conflict, message);

    public static Error Forbidden(string message)
        => new(ErrorCategory.Forbidden, message);

    public static Error Unauthorized(string message = "Kimlik dogrulama gerekli.")
        => new(ErrorCategory.Unauthorized, message);

    public static Error Domain(string message)
        => new(ErrorCategory.Domain, message);

    /// <summary>503 — the requested capability is temporarily unavailable (no silent fallback).</summary>
    public static Error Unavailable(string message, string code = CapabilityUnavailableCode)
        => new(ErrorCategory.Unavailable, message, Code: code);
}
