using BlogApp.Core.Application.Common.Interfaces.Services;
using BlogApp.Core.Application.Common.Utilities;
using BlogApp.Core.Application.Features.MediaFeature.Commands.UploadImageCommand;
using BlogApp.Core.Application.Features.MediaFeature.Commands.UploadImagesCommand;
using BlogApp.Core.Application.Features.MediaFeature.DTOs;
using Microsoft.Extensions.Logging.Abstractions;
using Xunit;

namespace BlogApp.Presentation.Api.Tests.Media;

public sealed class MediaUploadHandlerTests
{
    [Fact]
    public async Task Batch_PreservesPartialSuccessForInvalidFilesAndStorageFailure()
    {
        var storage = new RecordingFileStorage
        {
            Upload = (_, name, _) => name == "failed.png"
                ? throw new IOException("intentional storage failure")
                : Task.FromResult(new ImageUploadResult { Url = "/uploads/images/valid.webp" })
        };
        using var valid = new MemoryStream(MediaTestData.PngHeader);
        using var invalid = new MemoryStream(MediaTestData.PngHeader);
        using var failed = new MemoryStream(MediaTestData.PngHeader);
        var handler = new UploadImagesCommandHandler(storage, NullLogger<UploadImagesCommandHandler>.Instance);

        var result = await handler.Handle(new UploadImagesCommandRequest
        {
            Files = [MediaTestData.File(valid), MediaTestData.File(invalid, "invalid.txt", "text/plain"),
                MediaTestData.File(failed, "failed.png")]
        }, CancellationToken.None);

        Assert.True(result.IsSuccess);
        Assert.Single(result.Value!.Uploaded);
        Assert.Equal(2, result.Value.Errors.Count);
        Assert.Equal(2, storage.Uploads.Count);
    }

    [Fact]
    public async Task Batch_DoesNotConvertCancellationIntoPartialSuccess()
    {
        var storage = new RecordingFileStorage
        {
            Upload = (_, _, _) => throw new OperationCanceledException("intentional cancellation")
        };
        using var stream = new MemoryStream(MediaTestData.PngHeader);
        var handler = new UploadImagesCommandHandler(storage, NullLogger<UploadImagesCommandHandler>.Instance);

        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => handler.Handle(
            new UploadImagesCommandRequest { Files = [MediaTestData.File(stream)] }, CancellationToken.None));
        Assert.Single(storage.Uploads);
    }

    [Fact]
    public async Task CancelledCommands_DoNotReadOrUploadFiles()
    {
        var storage = new RecordingFileStorage();
        using var stream = new MemoryStream(MediaTestData.PngHeader);
        var file = MediaTestData.File(stream);
        var token = new CancellationToken(canceled: true);
        var single = new UploadImageCommandHandler(storage, NullLogger<UploadImageCommandHandler>.Instance);
        var batch = new UploadImagesCommandHandler(storage, NullLogger<UploadImagesCommandHandler>.Instance);

        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => single.Handle(
            new UploadImageCommandRequest { File = file }, token));
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => batch.Handle(
            new UploadImagesCommandRequest { Files = [file] }, token));
        Assert.Empty(storage.Uploads);
        Assert.Equal(0, stream.Position);
    }

    [Fact]
    public async Task Batch_RejectsCountAndAggregateBeforeReadingStreams()
    {
        var storage = new RecordingFileStorage();
        var handler = new UploadImagesCommandHandler(storage, NullLogger<UploadImagesCommandHandler>.Instance);
        using var stream = new MemoryStream(MediaTestData.PngHeader);
        var file = MediaTestData.File(stream);
        var tooMany = await handler.Handle(new UploadImagesCommandRequest
        {
            Files = Enumerable.Repeat(file, ImageValidation.MaxBatchSize + 1).ToList()
        }, CancellationToken.None);
        var oversizedTotal = await handler.Handle(new UploadImagesCommandRequest
        {
            Files = [new FileUploadDto
            {
                Stream = stream, FileName = "large.png", ContentType = "image/png",
                Length = ImageValidation.MaxBatchFileSize + 1
            }]
        }, CancellationToken.None);

        Assert.True(tooMany.IsFailure);
        Assert.True(oversizedTotal.IsFailure);
        Assert.Empty(storage.Uploads);
        Assert.Equal(0, stream.Position);
    }
}

internal static class MediaTestData
{
    public static readonly byte[] PngHeader = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 1, 2, 3, 4];

    public static FileUploadDto File(Stream stream, string name = "valid.png", string type = "image/png") => new()
    {
        Stream = stream, FileName = name, ContentType = type, Length = stream.Length
    };
}

internal sealed class RecordingFileStorage : IFileStorageService
{
    public List<Stream> Uploads { get; } = [];
    public Func<Stream, string, CancellationToken, Task<ImageUploadResult>> Upload { get; init; } =
        (_, _, _) => Task.FromResult(new ImageUploadResult { Url = "/uploads/images/valid.webp" });

    public Task<ImageUploadResult> UploadImageAsync(Stream stream, string name, ImageUploadOptions? options = null,
        CancellationToken cancellationToken = default)
    {
        Uploads.Add(stream);
        return Upload(stream, name, cancellationToken);
    }

    public Task<string> UploadAsync(Stream stream, string name, string type, CancellationToken cancellationToken = default) =>
        throw new NotSupportedException();
    public Task<bool> DeleteAsync(string url, CancellationToken cancellationToken = default) =>
        throw new NotSupportedException();
    public Task<bool> ExistsAsync(string url, CancellationToken cancellationToken = default) =>
        throw new NotSupportedException();
}
