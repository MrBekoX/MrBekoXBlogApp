namespace BlogApp.Core.Application.Common.Errors;

/// <summary>
/// Logical error categories. Used to translate <see cref="Error"/> into HTTP status codes
/// at the API boundary without leaking exception types into the application layer.
/// </summary>
public enum ErrorCategory
{
    Validation = 0,    // 400 — request shape/content invalid
    Unauthorized = 1,  // 401 — no/invalid credentials
    Forbidden = 2,     // 403 — authenticated but not permitted
    NotFound = 3,      // 404 — entity does not exist
    Conflict = 4,      // 409 — state/uniqueness violation
    Domain = 5         // 400 fallback — generic domain rule violation
}
