using System.Diagnostics;
using BlogApp.Server.Application.Common.Interfaces.Services;
using MediatR;
using Microsoft.Extensions.Logging;

namespace BlogApp.Server.Application.Common.Behaviors;

/// <summary>
/// MediatR Pipeline için logging behavior
/// </summary>
public class LoggingBehavior<TRequest, TResponse> : IPipelineBehavior<TRequest, TResponse>
    where TRequest : notnull
{
    private readonly ILogger<LoggingBehavior<TRequest, TResponse>> _logger;
    private readonly ICurrentUserService _currentUserService;

    public LoggingBehavior(ILogger<LoggingBehavior<TRequest, TResponse>> logger, ICurrentUserService currentUserService)
    {
        _logger = logger;
        _currentUserService = currentUserService;
    }

    public async Task<TResponse> Handle(TRequest request, RequestHandlerDelegate<TResponse> next, CancellationToken cancellationToken)
    {
        var requestName = typeof(TRequest).Name;
        var correlationId = _currentUserService.CorrelationId ?? Guid.NewGuid().ToString();

        _logger.LogInformation("[START] {CorrelationId} Handling {RequestName}", correlationId, requestName);

        var stopwatch = Stopwatch.StartNew();

        try
        {
            var response = await next();

            stopwatch.Stop();

            if (stopwatch.ElapsedMilliseconds > 500)
            {
                _logger.LogWarning("[PERFORMANCE] {CorrelationId} {RequestName} took {ElapsedMilliseconds}ms",
                    correlationId, requestName, stopwatch.ElapsedMilliseconds);
            }

            _logger.LogInformation("[END] {CorrelationId} Handled {RequestName} in {ElapsedMilliseconds}ms",
                correlationId, requestName, stopwatch.ElapsedMilliseconds);

            return response;
        }
        catch (Exception ex)
        {
            stopwatch.Stop();

            _logger.LogError(ex, "[ERROR] {CorrelationId} {RequestName} failed after {ElapsedMilliseconds}ms",
                correlationId, requestName, stopwatch.ElapsedMilliseconds);

            throw;
        }
    }
}
