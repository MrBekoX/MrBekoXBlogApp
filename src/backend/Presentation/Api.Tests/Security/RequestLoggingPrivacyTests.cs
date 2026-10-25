using System.Text;
using BlogApp.Presentation.Api.Middlewares;
using Microsoft.AspNetCore.Http;
using Microsoft.Extensions.Logging;
using Xunit;

namespace BlogApp.Presentation.Api.Tests.Security;

public sealed class RequestLoggingPrivacyTests
{
    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task RequestMetadataNeverRetainsQueryHeadersOrBodyEvenWhenTheNextDelegateThrows(bool throws)
    {
        var logger = new CaptureLogger();
        var context = new DefaultHttpContext();
        context.Request.Method = "GET";
        context.Request.Path = "/api/v1/agent/runs";
        context.Request.QueryString = new QueryString(
            "?access_token=private-token-sentinel&q=private-question-sentinel&profile=private-profile-sentinel");
        context.Request.Headers.Authorization = "Bearer private-header-sentinel";
        context.Request.Body = new MemoryStream(Encoding.UTF8.GetBytes("private-body-sentinel"));
        var expected = new InvalidOperationException("private-exception-sentinel");
        var middleware = new RequestLoggingMiddleware(next =>
        {
            if (throws) throw expected;
            next.Response.StatusCode = StatusCodes.Status204NoContent;
            return Task.CompletedTask;
        }, logger);

        if (throws)
            Assert.Same(expected, await Assert.ThrowsAsync<InvalidOperationException>(() => middleware.InvokeAsync(context)));
        else
            await middleware.InvokeAsync(context);
        var exported = string.Join("\n", logger.Entries.SelectMany(entry =>
            new[] { entry.Text }.Concat(entry.Fields.Select(field => field.Value?.ToString() ?? string.Empty))));
        Assert.DoesNotContain("private-", exported);
        Assert.Contains("GET", exported);
        Assert.Contains("/api/v1/agent/runs", exported);
        Assert.All(logger.Entries, entry => Assert.DoesNotContain(entry.Fields, field => field.Key == "QueryString"));
        if (!throws)
        {
            Assert.Contains(logger.Entries, entry => entry.Fields.Any(field => field.Key == "StatusCode" && Equals(field.Value, 204)));
            Assert.Contains(logger.Entries, entry => entry.Fields.Any(field => field.Key == "Elapsed" && field.Value is long elapsed && elapsed >= 0));
        }
    }

    private sealed record Entry(string Text, IReadOnlyList<KeyValuePair<string, object?>> Fields);

    private sealed class CaptureLogger : ILogger<RequestLoggingMiddleware>
    {
        public List<Entry> Entries { get; } = [];
        public IDisposable? BeginScope<TState>(TState state) where TState : notnull => null;
        public bool IsEnabled(LogLevel logLevel) => true;
        public void Log<TState>(LogLevel logLevel, EventId eventId, TState state, Exception? exception,
            Func<TState, Exception?, string> formatter) => Entries.Add(new Entry(formatter(state, exception),
                state is IEnumerable<KeyValuePair<string, object?>> fields ? fields.ToArray() : []));
    }
}
