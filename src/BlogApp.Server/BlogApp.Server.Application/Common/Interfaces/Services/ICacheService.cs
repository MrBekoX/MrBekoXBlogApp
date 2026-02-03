using BlogApp.BuildingBlocks.Caching.Abstractions;

namespace BlogApp.Server.Application.Common.Interfaces.Services;

/// <summary>
/// Domain-specific cache service interface extending IHybridCacheService with:
/// - MediatR-scoped SWR for proper DI handling in background refreshes
///
/// For basic caching needs, use IBasicCacheService.
/// For generic hybrid caching, use IHybridCacheService.
/// </summary>
public interface ICacheService : IHybridCacheService
{
    /// <summary>
    /// Gets or sets a value using Stale-While-Revalidate pattern with proper DI scope handling.
    /// Background refresh creates a new DI scope and uses MediatR to re-execute the request.
    /// This avoids disposed DbContext issues in background tasks.
    /// </summary>
    /// <typeparam name="TRequest">The MediatR request type</typeparam>
    /// <typeparam name="TResponse">The response type</typeparam>
    /// <param name="key">Cache key</param>
    /// <param name="request">The request object to re-execute in background refresh</param>
    /// <param name="factory">Factory function to create value on cache miss</param>
    /// <param name="softExpiration">Time after which value becomes stale</param>
    /// <param name="hardExpiration">Time after which value is removed (defaults to 2x soft)</param>
    /// <param name="cancellationToken">Cancellation token</param>
    Task<TResponse> GetOrSetWithSwrAsync<TRequest, TResponse>(
        string key,
        TRequest request,
        Func<Task<TResponse>> factory,
        TimeSpan softExpiration,
        TimeSpan? hardExpiration = null,
        CancellationToken cancellationToken = default) where TRequest : class;
}
