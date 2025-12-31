using System.Diagnostics;
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

    public LoggingBehavior(ILogger<LoggingBehavior<TRequest, TResponse>> logger)
    {
        _logger = logger;
    }

    public async Task<TResponse> Handle(TRequest request, RequestHandlerDelegate<TResponse> next, CancellationToken cancellationToken)
    {
        var requestName = typeof(TRequest).Name;
        var requestGuid = Guid.NewGuid().ToString();

        _logger.LogInformation("[START] {RequestGuid} Handling {RequestName}", requestGuid, requestName);

        var stopwatch = Stopwatch.StartNew();

        try
        {
            var response = await next();

            stopwatch.Stop();

            if (stopwatch.ElapsedMilliseconds > 500)
            {
                _logger.LogWarning("[PERFORMANCE] {RequestGuid} {RequestName} took {ElapsedMilliseconds}ms",
                    requestGuid, requestName, stopwatch.ElapsedMilliseconds);
            }

            _logger.LogInformation("[END] {RequestGuid} Handled {RequestName} in {ElapsedMilliseconds}ms",
                requestGuid, requestName, stopwatch.ElapsedMilliseconds);

            return response;
        }
        catch (Exception ex)
        {
            stopwatch.Stop();

            _logger.LogError(ex, "[ERROR] {RequestGuid} {RequestName} failed after {ElapsedMilliseconds}ms",
                requestGuid, requestName, stopwatch.ElapsedMilliseconds);

            throw;
        }
    }
}

