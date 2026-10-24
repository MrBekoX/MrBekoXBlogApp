using System.Threading.RateLimiting;
using BlogApp.Core.Application.Common.Models;
using Microsoft.AspNetCore.RateLimiting;

namespace BlogApp.Presentation.Api.Extensions;

public static class ImageUploadAdmissionExtensions
{
    public const string PolicyName = "image-upload";

    public static IServiceCollection AddImageUploadAdmissionControl(this IServiceCollection services)
    {
        services.AddRateLimiter(options =>
        {
            options.RejectionStatusCode = StatusCodes.Status429TooManyRequests;
            // One shared lease covers form binding, bounded buffers, processing
            // and response creation for either image-upload endpoint.
            options.AddConcurrencyLimiter(PolicyName, limiter =>
            {
                limiter.PermitLimit = 1;
                limiter.QueueLimit = 0;
                limiter.QueueProcessingOrder = QueueProcessingOrder.OldestFirst;
            });
            options.OnRejected = async (context, cancellationToken) =>
            {
                await context.HttpContext.Response.WriteAsJsonAsync(
                    ApiResponse<object>.FailureResult("Another image upload is being processed. Please retry."),
                    cancellationToken: cancellationToken);
            };
        });
        return services;
    }
}
