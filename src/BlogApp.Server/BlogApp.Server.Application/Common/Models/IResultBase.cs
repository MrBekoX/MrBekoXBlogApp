using BlogApp.Server.Application.Common.Errors;

namespace BlogApp.Server.Application.Common.Models;

/// <summary>
/// Non-generic marker for <see cref="Result"/> / <see cref="Result{T}"/> so pipeline behaviors
/// can construct typed failure instances without knowing the value type at compile time.
/// </summary>
public interface IResultBase
{
    bool IsSuccess { get; }
    bool IsFailure { get; }
    Error? ErrorDetail { get; }
}
