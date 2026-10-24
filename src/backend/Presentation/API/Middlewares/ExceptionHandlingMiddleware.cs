using System.Net;
using System.Text.Json;
using BlogApp.Core.Application.Common.Models;
using BlogApp.Core.Domain.Exceptions;

namespace BlogApp.Presentation.Api.Middlewares;

/// <summary>
/// Global exception handling middleware
/// </summary>
public class ExceptionHandlingMiddleware
{
    private readonly RequestDelegate _next;
    private readonly ILogger<ExceptionHandlingMiddleware> _logger;

    public ExceptionHandlingMiddleware(RequestDelegate next, ILogger<ExceptionHandlingMiddleware> logger)
    {
        _next = next;
        _logger = logger;
    }

    public async Task InvokeAsync(HttpContext context)
    {
        try
        {
            await _next(context);
        }
        catch (OperationCanceledException) when (context.RequestAborted.IsCancellationRequested)
        {
            if (!context.Response.HasStarted)
                context.Response.StatusCode = 499;
        }
        catch (Exception ex)
        {
            await HandleExceptionAsync(context, ex);
        }
    }

    private async Task HandleExceptionAsync(HttpContext context, Exception exception)
    {
        var statusCode = HttpStatusCode.InternalServerError;
        var errors = new List<string>();

        switch (exception)
        {
            case BlogApp.Core.Domain.Exceptions.ValidationException validationEx:
                statusCode = HttpStatusCode.BadRequest;
                errors = validationEx.Errors.SelectMany(e => e.Value).ToList();
                var errorDetails = string.Join("; ", validationEx.Errors.Select(e => $"{e.Key}: {string.Join(", ", e.Value)}"));
                _logger.LogInformation(exception, "ValidationException reached middleware (post-refactor this should be rare): {Errors}", errorDetails);
                break;

            case NotFoundException notFoundEx:
                statusCode = HttpStatusCode.NotFound;
                errors.Add(notFoundEx.Message);
                _logger.LogWarning(exception, "Resource not found: {Message}", notFoundEx.Message);
                break;

            case ForbiddenException forbiddenEx:
                statusCode = HttpStatusCode.Forbidden;
                errors.Add(forbiddenEx.Message);
                _logger.LogWarning(exception, "Forbidden access: {Message}", forbiddenEx.Message);
                break;

            case ConflictException conflictEx:
                statusCode = HttpStatusCode.Conflict;
                errors.Add(conflictEx.Message);
                _logger.LogInformation(exception, "ConflictException reached middleware (post-refactor this should be rare): {Message}", conflictEx.Message);
                break;

            case UnauthorizedAccessException:
                statusCode = HttpStatusCode.Unauthorized;
                errors.Add("Unauthorized access");
                _logger.LogWarning(exception, "Unauthorized access attempt");
                break;

            case DomainException domainEx:
                statusCode = HttpStatusCode.BadRequest;
                errors.Add(domainEx.Message);
                _logger.LogWarning(exception, "Domain error: {Message}", domainEx.Message);
                break;

            case BadHttpRequestException badRequestEx:
                statusCode = (HttpStatusCode)badRequestEx.StatusCode;
                errors.Add(badRequestEx.InnerException?.Message ?? badRequestEx.Message);
                _logger.LogWarning(exception, "Bad request: {Message}", badRequestEx.Message);
                break;

            default:
                errors.Add("An unexpected error occurred. Please try again later.");
                _logger.LogError(exception, "Unhandled exception occurred");
                break;
        }

        context.Response.ContentType = "application/json";
        context.Response.StatusCode = (int)statusCode;

        var response = ApiResponse<object>.FailureResult(errors);

        var jsonOptions = new JsonSerializerOptions
        {
            PropertyNamingPolicy = JsonNamingPolicy.CamelCase
        };

        await context.Response.WriteAsync(JsonSerializer.Serialize(response, jsonOptions));
    }
}

public static class ExceptionHandlingMiddlewareExtensions
{
    public static IApplicationBuilder UseExceptionHandling(this IApplicationBuilder builder)
    {
        return builder.UseMiddleware<ExceptionHandlingMiddleware>();
    }
}

