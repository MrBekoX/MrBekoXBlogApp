using BlogApp.Server.Application.Common.Errors;
using BlogApp.Server.Application.Common.Models;

namespace BlogApp.Server.Api.Helpers;

/// <summary>
/// Maps <see cref="Result"/> / <see cref="Result{T}"/> to ASP.NET Core <see cref="IResult"/>
/// with the correct HTTP status code and an <see cref="ApiResponse{T}"/> envelope.
/// </summary>
public static class ResultHttpExtensions
{
    public static IResult ToHttpResult<T>(
        this Result<T> result,
        PaginationMeta? pagination = null)
    {
        if (result.IsSuccess)
        {
            var success = pagination is null
                ? ApiResponse<T>.SuccessResult(result.Value!)
                : ApiResponse<T>.SuccessResult(result.Value!, pagination);
            return Results.Ok(success);
        }

        var status = MapStatus(result.ErrorDetail);
        var body = ApiResponse<T>.FailureResult(result.Errors, result.ErrorDetail);
        return Results.Json(body, statusCode: status);
    }

    public static IResult ToHttpResult(this Result result)
    {
        if (result.IsSuccess)
            return Results.Ok(ApiResponse<object>.SuccessResult(new { }));

        var status = MapStatus(result.ErrorDetail);
        var body = ApiResponse<object>.FailureResult(result.Errors, result.ErrorDetail);
        return Results.Json(body, statusCode: status);
    }

    private static int MapStatus(Error? error) => error?.Category switch
    {
        ErrorCategory.Validation => StatusCodes.Status400BadRequest,
        ErrorCategory.Unauthorized => StatusCodes.Status401Unauthorized,
        ErrorCategory.Forbidden => StatusCodes.Status403Forbidden,
        ErrorCategory.NotFound => StatusCodes.Status404NotFound,
        ErrorCategory.Conflict => StatusCodes.Status409Conflict,
        ErrorCategory.Domain => StatusCodes.Status400BadRequest,
        _ => StatusCodes.Status400BadRequest
    };
}
