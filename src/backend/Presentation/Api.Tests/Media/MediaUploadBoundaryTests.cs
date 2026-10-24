using System.Net;
using System.Security.Claims;
using System.Security.Cryptography;
using System.Text;
using Asp.Versioning;
using BlogApp.Core.Application.Common.Interfaces;
using BlogApp.Core.Application.Common.Interfaces.Services;
using BlogApp.Core.Application.Common.Utilities;
using BlogApp.Core.Application.Features.MediaFeature.Commands.UploadImageCommand;
using BlogApp.Presentation.Api.Endpoints;
using BlogApp.Presentation.Api.Extensions;
using BlogApp.Presentation.Api.Middlewares;
using MediatR;
using Microsoft.AspNetCore.Antiforgery;
using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.DataProtection;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Http.Features;
using Microsoft.AspNetCore.TestHost;
using Microsoft.Extensions.DependencyInjection;
using Xunit;

namespace BlogApp.Presentation.Api.Tests.Media;

public sealed class MediaUploadBoundaryTests
{
    private const string SinglePath = "/api/v1/media/upload/image";
    private const string BatchPath = "/api/v1/media/upload/images";

    [Fact]
    public async Task MetadataLimits_RejectBeforeOpeningAnyFile()
    {
        await using var app = await StartAsync(new RecordingFileStorage());
        var oversized = new TestFormFile(ImageValidation.MaxFileSize + 1);
        Assert.Equal(400, (await SendAsync(app, SinglePath, [oversized])).Response.StatusCode);
        Assert.Equal(0, oversized.OpenCount);

        var first = new TestFormFile(12);
        Assert.Equal(400, (await SendAsync(app, BatchPath, [first, oversized])).Response.StatusCode);
        Assert.Equal(0, first.OpenCount);
        Assert.Equal(0, oversized.OpenCount);

        var tooMany = Enumerable.Range(0, ImageValidation.MaxBatchSize + 1)
            .Select(_ => new TestFormFile(12)).ToArray();
        Assert.Equal(400, (await SendAsync(app, BatchPath, tooMany)).Response.StatusCode);
        Assert.All(tooMany, file => Assert.Equal(0, file.OpenCount));
    }

    [Fact]
    public async Task ActualStreamLimit_StopsAtOneExtraByteAndDisposesSource()
    {
        var storage = new RecordingFileStorage();
        await using var app = await StartAsync(storage);
        var source = new SizedReadStream(ImageValidation.MaxFileSize + 1024);
        var file = new TestFormFile(1, () => source);

        var response = await SendAsync(app, SinglePath, [file]);

        Assert.Equal(413, response.Response.StatusCode);
        Assert.Equal(ImageValidation.MaxFileSize + 1, source.BytesRead);
        Assert.True(source.Disposed);
        Assert.Empty(storage.Uploads);
    }

    [Fact]
    public async Task Success_HashesTheSingleBoundedReadAndDisposesCommandBuffer()
    {
        var storage = new RecordingFileStorage();
        var capture = new CaptureCommand();
        await using var app = await StartAsync(storage, capture);
        var source = new TrackingMemoryStream(MediaTestData.PngHeader);
        var file = new TestFormFile(source.Length, () => source);

        var response = await SendAsync(app, SinglePath, [file]);

        Assert.Equal(200, response.Response.StatusCode);
        Assert.Equal(1, file.OpenCount);
        Assert.True(source.Disposed);
        var buffer = Assert.Single(storage.Uploads);
        Assert.False(buffer.CanRead);
        var metadata = Encoding.UTF8.GetBytes($"generateThumbnail=null{file.FileName}{file.ContentType}{file.Length}");
        var expected = Convert.ToHexString(SHA256.HashData([.. metadata, .. MediaTestData.PngHeader]));
        Assert.Equal(expected, capture.Hash);
    }

    [Theory]
    [InlineData(false, false)]
    [InlineData(true, false)]
    [InlineData(false, true)]
    [InlineData(true, true)]
    public async Task StorageFailureOrCancellation_DisposesEveryCommandBuffer(bool batch, bool cancellation)
    {
        var storage = new RecordingFileStorage { Upload = (_, _, _) => cancellation
            ? throw new OperationCanceledException("intentional cancellation")
            : throw new IOException("intentional failure") };
        await using var app = await StartAsync(storage);
        TestFormFile[] files = batch ? [new(12), new(12)] : [new(12)];

        var response = await SendAsync(app, batch ? BatchPath : SinglePath, files);

        Assert.Equal(cancellation ? 500 : batch ? 200 : 500, response.Response.StatusCode);
        Assert.Equal(cancellation ? 1 : files.Length, storage.Uploads.Count);
        Assert.All(storage.Uploads, stream => Assert.False(stream.CanRead));
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task CopyFailureOrCancellation_DisposesSourcesAndReleasesAdmission(bool cancellation)
    {
        var storage = new RecordingFileStorage();
        await using var app = await StartAsync(storage);
        var firstSource = new TrackingMemoryStream(MediaTestData.PngHeader);
        var failedSource = new FailedReadStream(cancellation);

        var response = await SendAsync(app, BatchPath,
            [new TestFormFile(12, () => firstSource), new TestFormFile(12, () => failedSource)]);

        Assert.Equal(500, response.Response.StatusCode);
        Assert.True(firstSource.Disposed);
        Assert.True(failedSource.Disposed);
        Assert.Empty(storage.Uploads);
        Assert.Equal(200, (await SendAsync(app, SinglePath, [new TestFormFile(12)])).Response.StatusCode);
    }

    [Fact]
    public async Task OneAdmissionPolicy_CoversBothRoutesBeforeBindingOrCopying()
    {
        var entered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var release = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var storage = new RecordingFileStorage { Upload = async (_, _, token) =>
        {
            entered.TrySetResult();
            await release.Task.WaitAsync(token);
            return new ImageUploadResult { Url = "/uploads/images/valid.webp" };
        } };
        await using var app = await StartAsync(storage);
        var active = SendAsync(app, SinglePath, [new TestFormFile(12)]);
        try
        {
            await entered.Task.WaitAsync(TimeSpan.FromSeconds(5));
            var blocked = new TestFormFile(12);
            Assert.Equal(429, (await SendAsync(app, BatchPath, [blocked])).Response.StatusCode);
            Assert.Equal(0, blocked.OpenCount);
        }
        finally
        {
            release.TrySetResult();
            await active;
        }
    }

    [Fact]
    public async Task MultipartParser_EnforcesPerFileLimitBeforeCommandExecution()
    {
        var storage = new RecordingFileStorage();
        await using var app = await StartAsync(storage);
        using var client = app.GetTestClient();
        using var form = new MultipartFormDataContent();
        form.Add(new StreamContent(new SizedReadStream(ImageValidation.MaxFileSize + 1)), "file", "large.png");

        using var response = await client.PostAsync(SinglePath, form);

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
        Assert.Empty(storage.Uploads);
    }

    private static async Task<WebApplication> StartAsync(RecordingFileStorage storage, CaptureCommand? capture = null)
    {
        // EmptyBuilder avoids reading appsettings, environment providers or developer secrets.
        var builder = WebApplication.CreateEmptyBuilder(new WebApplicationOptions
        {
            EnvironmentName = "Testing", ApplicationName = typeof(MediaUploadBoundaryTests).Assembly.FullName
        });
        builder.WebHost.UseTestServer();
        builder.Services.AddRouting();
        builder.Services.AddLogging();
        builder.Services.AddAuthorization();
        builder.Services.AddAntiforgery();
        builder.Services.AddDataProtection().UseEphemeralDataProtectionProvider();
        builder.Services.AddSingleton<IAntiforgery, AcceptAntiforgery>();
        builder.Services.AddSingleton<IFileStorageService>(storage);
        builder.Services.AddSingleton(capture ?? new CaptureCommand());
        builder.Services.AddMediatR(options =>
        {
            options.RegisterServicesFromAssembly(typeof(UploadImageCommandHandler).Assembly);
            options.AddOpenBehavior(typeof(CaptureCommandBehavior<,>));
        });
        builder.Services.AddApiVersioning(options =>
        {
            options.DefaultApiVersion = new ApiVersion(1, 0);
            options.AssumeDefaultVersionWhenUnspecified = true;
            options.ApiVersionReader = new UrlSegmentApiVersionReader();
        });
        builder.Services.AddImageUploadAdmissionControl();
        var app = builder.Build();
        app.UseExceptionHandling();
        app.UseRouting();
        app.Use((context, next) =>
        {
            context.User = new ClaimsPrincipal(new ClaimsIdentity([new Claim(ClaimTypes.Role, "Admin")], "Test"));
            return next(context);
        });
        app.UseAuthorization();
        app.UseRateLimiter();
        app.UseAntiforgery();
        app.RegisterMediaEndpoints();
        await app.StartAsync();
        return app;
    }

    private static Task<HttpContext> SendAsync(WebApplication app, string path, IReadOnlyCollection<IFormFile> files) =>
        app.GetTestServer().SendAsync(context =>
        {
            context.Request.Method = HttpMethods.Post;
            context.Request.Path = path;
            context.Request.ContentType = "multipart/form-data; boundary=test";
            var formFiles = new FormFileCollection();
            foreach (var file in files) formFiles.Add(file);
            context.Features.Set<IFormFeature>(new PresetFormFeature(new FormCollection(
                new Dictionary<string, Microsoft.Extensions.Primitives.StringValues>(), formFiles)));
        });

    private sealed class PresetFormFeature(IFormCollection form) : IFormFeature
    {
        public bool HasFormContentType => true;
        public IFormCollection? Form { get; set; } = form;
        public IFormCollection ReadForm() => Form!;
        public Task<IFormCollection> ReadFormAsync(CancellationToken cancellationToken) => Task.FromResult(Form!);
    }

    private sealed class AcceptAntiforgery : IAntiforgery
    {
        public AntiforgeryTokenSet GetAndStoreTokens(HttpContext context) => new("test", "test", "test", "test");
        public AntiforgeryTokenSet GetTokens(HttpContext context) => GetAndStoreTokens(context);
        public Task<bool> IsRequestValidAsync(HttpContext context) => Task.FromResult(true);
        public Task ValidateRequestAsync(HttpContext context) => Task.CompletedTask;
        public void SetCookieTokenAndHeader(HttpContext context) { }
    }

    private sealed class TestFormFile(long length, Func<Stream>? open = null) : IFormFile
    {
        public int OpenCount { get; private set; }
        public string ContentType => "image/png";
        public string ContentDisposition => "form-data; name=\"file\"; filename=\"valid.png\"";
        public IHeaderDictionary Headers { get; } = new HeaderDictionary();
        public long Length => length;
        public string Name => "file";
        public string FileName => "valid.png";
        public Stream OpenReadStream() { OpenCount++; return open?.Invoke() ?? new TrackingMemoryStream(MediaTestData.PngHeader); }
        public void CopyTo(Stream target) { using var source = OpenReadStream(); source.CopyTo(target); }
        public async Task CopyToAsync(Stream target, CancellationToken token = default)
        { await using var source = OpenReadStream(); await source.CopyToAsync(target, token); }
    }

    private sealed class TrackingMemoryStream(byte[] data) : MemoryStream(data)
    {
        public bool Disposed { get; private set; }
        protected override void Dispose(bool disposing) { Disposed = true; base.Dispose(disposing); }
    }

    private sealed class FailedReadStream(bool cancellation) : MemoryStream
    {
        public bool Disposed { get; private set; }
        public override ValueTask<int> ReadAsync(Memory<byte> buffer, CancellationToken token = default) =>
            cancellation ? ValueTask.FromException<int>(new OperationCanceledException("intentional cancellation"))
                : ValueTask.FromException<int>(new IOException("intentional copy failure"));
        protected override void Dispose(bool disposing) { Disposed = true; base.Dispose(disposing); }
    }

    private sealed class SizedReadStream(long length) : Stream
    {
        public long BytesRead { get; private set; }
        public bool Disposed { get; private set; }
        public override bool CanRead => !Disposed;
        public override bool CanSeek => false;
        public override bool CanWrite => false;
        public override long Length => length;
        public override long Position { get => BytesRead; set => throw new NotSupportedException(); }
        public override int Read(byte[] buffer, int offset, int count)
        {
            var read = (int)Math.Min(count, length - BytesRead);
            buffer.AsSpan(offset, read).Clear();
            BytesRead += read;
            return read;
        }
        public override ValueTask<int> ReadAsync(Memory<byte> buffer, CancellationToken token = default)
        {
            token.ThrowIfCancellationRequested();
            var read = (int)Math.Min(buffer.Length, length - BytesRead);
            buffer.Span[..read].Clear();
            BytesRead += read;
            return ValueTask.FromResult(read);
        }
        protected override void Dispose(bool disposing) { Disposed = true; base.Dispose(disposing); }
        public override void Flush() => throw new NotSupportedException();
        public override long Seek(long offset, SeekOrigin origin) => throw new NotSupportedException();
        public override void SetLength(long value) => throw new NotSupportedException();
        public override void Write(byte[] buffer, int offset, int count) => throw new NotSupportedException();
    }
}

internal sealed class CaptureCommand
{
    public string? Hash { get; set; }
}

internal sealed class CaptureCommandBehavior<TRequest, TResponse>(CaptureCommand capture) : IPipelineBehavior<TRequest, TResponse>
    where TRequest : notnull
{
    public Task<TResponse> Handle(TRequest request, RequestHandlerDelegate<TResponse> next, CancellationToken cancellationToken)
    {
        if (request is IIdempotentCommand command) capture.Hash = command.CustomRequestHash;
        return next(cancellationToken);
    }
}
