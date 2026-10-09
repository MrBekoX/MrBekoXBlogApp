using System.Collections.Concurrent;
using System.Linq.Expressions;
using System.Reflection;
using BlogApp.Core.Application.Common.Errors;
using BlogApp.Core.Application.Common.Models;

namespace BlogApp.Core.Application.Common.Behaviors;

/// <summary>
/// Builds and caches a delegate that constructs <see cref="Result"/>/<see cref="Result{T}"/> failures
/// for any closed response type. Behaviors call this when they need to return a typed failure
/// without knowing the underlying value type at compile time.
/// </summary>
internal static class ResultFactory
{
    private static readonly ConcurrentDictionary<Type, Func<Error, object>> Cache = new();

    /// <summary>
    /// Returns a failure instance of <typeparamref name="TResponse"/> carrying the provided <see cref="Error"/>.
    /// Throws <see cref="InvalidOperationException"/> if <typeparamref name="TResponse"/> is not assignable to <see cref="IResultBase"/>.
    /// </summary>
    public static TResponse Failure<TResponse>(Error error)
    {
        var factory = Cache.GetOrAdd(typeof(TResponse), BuildFactory);
        return (TResponse)factory(error);
    }

    public static bool IsResult(Type responseType)
        => typeof(IResultBase).IsAssignableFrom(responseType);

    private static Func<Error, object> BuildFactory(Type responseType)
    {
        if (!typeof(IResultBase).IsAssignableFrom(responseType))
        {
            throw new InvalidOperationException(
                $"ResultFactory only supports IResultBase response types; {responseType} is not assignable to IResultBase.");
        }

        // Find: public static TResponse Failure(Error error)
        var method = responseType.GetMethod(
            nameof(Result.Failure),
            BindingFlags.Public | BindingFlags.Static,
            binder: null,
            types: new[] { typeof(Error) },
            modifiers: null);

        if (method is null)
        {
            throw new InvalidOperationException(
                $"{responseType} does not expose a static Failure(Error) method.");
        }

        var errorParam = Expression.Parameter(typeof(Error), "error");
        var call = Expression.Call(method, errorParam);
        var cast = Expression.Convert(call, typeof(object));
        return Expression.Lambda<Func<Error, object>>(cast, errorParam).Compile();
    }
}
