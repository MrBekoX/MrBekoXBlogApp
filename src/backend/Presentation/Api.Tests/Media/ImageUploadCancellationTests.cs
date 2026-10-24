using System.Text.Json;
using BlogApp.Presentation.Api.Middlewares;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Http.Features;
using Microsoft.Extensions.Logging;
using Xunit;

namespace BlogApp.Presentation.Api.Tests.Media;

public sealed class ImageUploadCancellationTests
{
    [Fact]
    public async Task AbortedRequest_Returns499WithoutWritingOrLoggingAnError()
    {
        using var cancellation = new CancellationTokenSource();
        using var body = new MemoryStream();
        var context = new DefaultHttpContext { RequestAborted = cancellation.Token };
        context.Response.Body = body;
        var logger = new RecordingLogger();
        var middleware = new ExceptionHandlingMiddleware(_ =>
        {
            cancellation.Cancel();
            throw new OperationCanceledException(cancellation.Token);
        }, logger);

        await middleware.InvokeAsync(context);

        Assert.Equal(499, context.Response.StatusCode);
        Assert.Equal(0, body.Length);
        Assert.Null(context.Response.ContentType);
        Assert.Empty(logger.Levels);
    }

    [Fact]
    public async Task AbortedStartedResponse_PreservesItsStatusAndBody()
    {
        using var body = new MemoryStream();
        body.Write([1, 2, 3]);
        var context = new DefaultHttpContext();
        var response = new StartedResponseFeature(body) { StatusCode = StatusCodes.Status202Accepted };
        response.Headers["X-Test"] = "preserved";
        context.Features.Set<IHttpResponseFeature>(response);
        context.RequestAborted = new CancellationToken(canceled: true);
        var logger = new RecordingLogger();
        var middleware = new ExceptionHandlingMiddleware(_ => throw new OperationCanceledException(), logger);

        await middleware.InvokeAsync(context);

        Assert.True(context.Response.HasStarted);
        Assert.Equal(StatusCodes.Status202Accepted, context.Response.StatusCode);
        Assert.Equal(new byte[] { 1, 2, 3 }, body.ToArray());
        Assert.Single(context.Response.Headers);
        Assert.Equal("preserved", context.Response.Headers["X-Test"].ToString());
        Assert.Empty(logger.Levels);
    }

    [Fact]
    public async Task CancellationFaultOnActiveRequest_RemainsAGeneric500()
    {
        using var body = new MemoryStream();
        var context = new DefaultHttpContext();
        context.Response.Body = body;
        var logger = new RecordingLogger();
        var middleware = new ExceptionHandlingMiddleware(_ =>
            throw new OperationCanceledException("internal operation failed"), logger);

        await middleware.InvokeAsync(context);

        Assert.Equal(StatusCodes.Status500InternalServerError, context.Response.StatusCode);
        Assert.Equal("application/json", context.Response.ContentType);
        body.Position = 0;
        using var json = await JsonDocument.ParseAsync(body);
        Assert.False(json.RootElement.GetProperty("success").GetBoolean());
        Assert.DoesNotContain("internal operation failed", json.RootElement.GetRawText());
        Assert.Contains(LogLevel.Error, logger.Levels);
    }

    private sealed class RecordingLogger : ILogger<ExceptionHandlingMiddleware>
    {
        public List<LogLevel> Levels { get; } = [];
        public IDisposable? BeginScope<TState>(TState state) where TState : notnull => null;
        public bool IsEnabled(LogLevel level) => true;
        public void Log<TState>(LogLevel level, EventId eventId, TState state, Exception? exception,
            Func<TState, Exception?, string> formatter) => Levels.Add(level);
    }

    private sealed class StartedResponseFeature(Stream body) : IHttpResponseFeature
    {
        public int StatusCode { get; set; }
        public string? ReasonPhrase { get; set; }
        public IHeaderDictionary Headers { get; set; } = new HeaderDictionary();
        public Stream Body { get; set; } = body;
        public bool HasStarted => true;
        public void OnStarting(Func<object, Task> callback, object state) { }
        public void OnCompleted(Func<object, Task> callback, object state) { }
    }
}
