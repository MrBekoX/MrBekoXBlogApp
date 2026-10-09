using System.Text.Json.Serialization;
using BlogApp.Core.Application.Common.Errors;

namespace BlogApp.Core.Application.Common.Models;

/// <summary>
/// Non-generic Result. Prefer <see cref="Result{T}"/> in handlers — this exists for void-like flows.
/// </summary>
public class Result : IResultBase
{
    public bool IsSuccess { get; set; }
    public bool IsFailure => !IsSuccess;

    /// <summary>Legacy primary error message — auto-mirrored from <see cref="ErrorDetail"/>.</summary>
    public string? Error { get; set; }

    /// <summary>Legacy flat error list — auto-mirrored from <see cref="ErrorDetail"/>.</summary>
    public List<string> Errors { get; set; } = new();

    /// <summary>Rich error descriptor (category + message + optional field errors). Null on success.</summary>
    public Error? ErrorDetail { get; set; }

    [JsonConstructor]
    public Result(bool isSuccess, string? error)
    {
        IsSuccess = isSuccess;
        Error = error;
        if (!string.IsNullOrEmpty(error))
        {
            Errors.Add(error);
            ErrorDetail = new Error(ErrorCategory.Domain, error);
        }
    }

    public Result(bool isSuccess, List<string> errors)
    {
        IsSuccess = isSuccess;
        Errors = errors;
        Error = errors.FirstOrDefault();
        if (errors.Count > 0)
            ErrorDetail = new Error(ErrorCategory.Domain, Error ?? string.Empty);
    }

    protected Result(Error error)
    {
        IsSuccess = false;
        ErrorDetail = error;
        Error = error.Message;
        if (error.FieldErrors is { Count: > 0 })
            Errors = error.FieldErrors.SelectMany(kv => kv.Value).ToList();
        else
            Errors = new List<string> { error.Message };
    }

    public static Result Success() => new(true, (string?)null);
    public static Result Failure(string error) => new(false, error);
    public static Result Failure(List<string> errors) => new(false, errors);
    public static Result Failure(Error error) => new(error);

    public static Result<T> Success<T>(T value) => Result<T>.Success(value);
    public static Result<T> Failure<T>(string error) => Result<T>.Failure(error);
    public static Result<T> Failure<T>(Error error) => Result<T>.Failure(error);
}

public class Result<T> : Result
{
    public T? Value { get; set; }

    [JsonConstructor]
    public Result(bool isSuccess, string? error, T? value) : base(isSuccess, error)
    {
        Value = value;
    }

    private Result(T value) : base(true, (string?)null)
    {
        Value = value;
    }

    private Result(string error) : base(false, error)
    {
        Value = default;
    }

    private Result(List<string> errors) : base(false, errors)
    {
        Value = default;
    }

    private Result(Error error) : base(error)
    {
        Value = default;
    }

    public static Result<T> Success(T value) => new(value);
    public new static Result<T> Failure(string error) => new(error);
    public new static Result<T> Failure(List<string> errors) => new(errors);
    public new static Result<T> Failure(Error error) => new(error);

    public static implicit operator Result<T>(T value) => Success(value);
}
