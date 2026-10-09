using BlogApp.Core.Application.Common.Errors;
using BlogApp.Core.Application.Common.Models;
using FluentValidation;
using MediatR;

namespace BlogApp.Core.Application.Common.Behaviors;

/// <summary>
/// Runs FluentValidation rules and short-circuits the pipeline with a typed
/// <see cref="Result{T}"/> failure carrying field-error mapping when invalid.
/// Does NOT throw — exceptions on the validation hot path are wasteful and
/// erase field-to-error correlation.
/// </summary>
public class ValidationBehavior<TRequest, TResponse> : IPipelineBehavior<TRequest, TResponse>
    where TRequest : notnull
{
    private readonly IEnumerable<IValidator<TRequest>> _validators;

    public ValidationBehavior(IEnumerable<IValidator<TRequest>> validators)
    {
        _validators = validators;
    }

    public async Task<TResponse> Handle(
        TRequest request,
        RequestHandlerDelegate<TResponse> next,
        CancellationToken cancellationToken)
    {
        if (!_validators.Any())
            return await next(cancellationToken);

        var context = new ValidationContext<TRequest>(request);
        var validationResults = await Task.WhenAll(
            _validators.Select(v => v.ValidateAsync(context, cancellationToken)));

        var failures = validationResults
            .SelectMany(r => r.Errors)
            .Where(f => f != null)
            .ToList();

        if (failures.Count == 0)
            return await next(cancellationToken);

        var fieldErrors = failures
            .GroupBy(e => e.PropertyName)
            .ToDictionary(
                g => g.Key,
                g => g.Select(e => e.ErrorMessage).ToArray()) as IReadOnlyDictionary<string, string[]>;

        var error = Error.Validation(fieldErrors!);

        if (!ResultFactory.IsResult(typeof(TResponse)))
        {
            // TResponse is not Result-derived — preserve old throw semantics so non-Result
            // request types (rare, e.g. INotification handlers) still get a clear error.
            throw new Domain.Exceptions.ValidationException(
                fieldErrors!.ToDictionary(kv => kv.Key, kv => kv.Value));
        }

        return ResultFactory.Failure<TResponse>(error);
    }
}

