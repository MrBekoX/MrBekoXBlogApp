namespace BlogApp.Server.Application.Common.Interfaces;

/// <summary>
/// Marker interface for commands that support idempotency via Idempotency-Key header.
/// Commands implementing this interface will be automatically wrapped by IdempotencyBehavior
/// in the MediatR pipeline.
/// </summary>
public interface IIdempotentCommand
{
    /// <summary>
    /// Unique operation identifier from the Idempotency-Key header.
    /// </summary>
    string OperationId { get; }

    /// <summary>
    /// Logical endpoint name for idempotency tracking (e.g. "posts.create", "categories.update").
    /// </summary>
    string IdempotencyEndpointName { get; }

    /// <summary>
    /// Optional custom request hash. When null, IdempotencyBehavior computes hash from the full request.
    /// Use for requests where the body alone is insufficient (e.g. cookie-based refresh token).
    /// </summary>
    string? CustomRequestHash => null;
}
