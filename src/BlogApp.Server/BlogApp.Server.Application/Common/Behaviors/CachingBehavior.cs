using BlogApp.Server.Application.Common.Interfaces;
using MediatR;
using Microsoft.Extensions.Logging;

namespace BlogApp.Server.Application.Common.Behaviors;

/// <summary>
/// Cache'lenebilir request'ler için interface
/// </summary>
public interface ICacheableQuery
{
    string CacheKey { get; }
    TimeSpan? CacheDuration { get; }
}

/// <summary>
/// MediatR Pipeline için caching behavior
/// </summary>
public class CachingBehavior<TRequest, TResponse> : IPipelineBehavior<TRequest, TResponse>
    where TRequest : ICacheableQuery
{
    private readonly ICacheService _cacheService;
    private readonly ILogger<CachingBehavior<TRequest, TResponse>> _logger;

    public CachingBehavior(ICacheService cacheService, ILogger<CachingBehavior<TRequest, TResponse>> logger)
    {
        _cacheService = cacheService;
        _logger = logger;
    }

    public async Task<TResponse> Handle(TRequest request, RequestHandlerDelegate<TResponse> next, CancellationToken cancellationToken)
    {
        var cacheKey = request.CacheKey;

        var cachedResponse = await _cacheService.GetAsync<TResponse>(cacheKey, cancellationToken);

        if (cachedResponse is not null)
        {
            _logger.LogDebug("Cache hit for {CacheKey}", cacheKey);
            return cachedResponse;
        }

        _logger.LogDebug("Cache miss for {CacheKey}", cacheKey);

        var response = await next();

        var duration = request.CacheDuration ?? TimeSpan.FromMinutes(5);
        await _cacheService.SetAsync(cacheKey, response, duration, cancellationToken);

        return response;
    }
}
