using System.Text.Json.Serialization;
using BlogApp.Core.Application.Common.Errors;

namespace BlogApp.Core.Application.Common.Models;

/// <summary>
/// Standart API response modeli
/// </summary>
public class ApiResponse<T>
{
    public bool Success { get; set; }
    public T? Data { get; set; }
    public string? Message { get; set; }
    public List<string> Errors { get; set; } = new();

    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public ErrorCategory? Category { get; set; }

    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public IReadOnlyDictionary<string, string[]>? FieldErrors { get; set; }

    /// <summary>Machine-readable error code from <see cref="Error.Code"/> (e.g. capability_unavailable).</summary>
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? Code { get; set; }

    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public PaginationMeta? Pagination { get; set; }

    public static ApiResponse<T> SuccessResult(T data, string? message = null)
    {
        return new ApiResponse<T>
        {
            Success = true,
            Data = data,
            Message = message
        };
    }

    public static ApiResponse<T> SuccessResult(T data, PaginationMeta pagination, string? message = null)
    {
        return new ApiResponse<T>
        {
            Success = true,
            Data = data,
            Message = message,
            Pagination = pagination
        };
    }

    public static ApiResponse<T> FailureResult(string error)
    {
        return new ApiResponse<T>
        {
            Success = false,
            Errors = new List<string> { error }
        };
    }

    public static ApiResponse<T> FailureResult(List<string> errors)
    {
        return new ApiResponse<T>
        {
            Success = false,
            Errors = errors
        };
    }

    public static ApiResponse<T> FailureResult(List<string> errors, Error? errorDetail)
    {
        return new ApiResponse<T>
        {
            Success = false,
            Errors = errors,
            Category = errorDetail?.Category,
            FieldErrors = errorDetail?.FieldErrors,
            Code = errorDetail?.Code
        };
    }

    public static ApiResponse<T> FailureResult(Error error)
    {
        var errors = error.FieldErrors is { Count: > 0 }
            ? error.FieldErrors.SelectMany(kv => kv.Value).ToList()
            : new List<string> { error.Message };

        return FailureResult(errors, error);
    }
}

/// <summary>
/// Pagination meta bilgileri
/// </summary>
public class PaginationMeta
{
    public int CurrentPage { get; set; }
    public int PageSize { get; set; }
    public int TotalPages { get; set; }
    public int TotalCount { get; set; }
    public bool HasPrevious { get; set; }
    public bool HasNext { get; set; }

    public static PaginationMeta FromPaginatedList<T>(PaginatedList<T> list)
    {
        return new PaginationMeta
        {
            CurrentPage = list.PageNumber,
            PageSize = list.PageSize,
            TotalPages = list.TotalPages,
            TotalCount = list.TotalCount,
            HasPrevious = list.HasPreviousPage,
            HasNext = list.HasNextPage
        };
    }
}

