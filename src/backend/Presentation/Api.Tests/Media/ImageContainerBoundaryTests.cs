using System.Buffers.Binary;
using System.Reflection;
using BlogApp.Core.Domain.Exceptions;
using BlogApp.Infrastructure.Services;
using SixLabors.ImageSharp;
using SixLabors.ImageSharp.PixelFormats;
using Xunit;

namespace BlogApp.Presentation.Api.Tests.Media;

public sealed class ImageContainerBoundaryTests
{
    [Fact]
    public void PngIccEnvelopes_AreRemovedBeforeAnyProfileDecompression()
    {
        using var image = new Image<Rgba32>(2, 2, new Rgba32(10, 20, 30, 90));
        using var original = new MemoryStream();
        image.SaveAsPng(original);
        var png = original.ToArray();
        byte[] opaqueProfileData = [112, 0, 0, 1, 2, 3];
        var chunk = new byte[12 + opaqueProfileData.Length];
        BinaryPrimitives.WriteUInt32BigEndian(chunk, (uint)opaqueProfileData.Length);
        "iCCP"u8.CopyTo(chunk.AsSpan(4));
        opaqueProfileData.CopyTo(chunk, 8);

        using var input = new MemoryStream();
        input.Write(png.AsSpan(0, png.Length - 12));
        input.Write(chunk);
        input.Write(chunk);
        input.Write(png.AsSpan(png.Length - 12));
        input.Position = 0;

        var policy = typeof(FileStorageService).Assembly.GetType(
            "BlogApp.Infrastructure.Services.Helpers.ImageProcessingSecurity", throwOnError: true)!;
        Assert.Equal(1, policy.GetMethod("CountPngFrames", BindingFlags.NonPublic | BindingFlags.Static)!
            .Invoke(null, [input, CancellationToken.None]));
        policy.GetMethod("RemovePngIccChunks", BindingFlags.NonPublic | BindingFlags.Static)!
            .Invoke(null, [input, CancellationToken.None]);

        Assert.Equal(png, input.ToArray());
        using var decoded = Image.Load<Rgba32>(input);
        Assert.Equal(new Rgba32(10, 20, 30, 90), decoded[0, 0]);
        Assert.Null(decoded.Metadata.IccProfile);
    }

    [Theory]
    [InlineData((byte)'0')]
    [InlineData((byte)0)]
    [InlineData((byte)255)]
    public void PngEnvelope_RejectsNonLetterChunkTypesBeforeDecoderResynchronization(byte invalidType)
    {
        using var image = new Image<Rgba32>(2, 2);
        using var encoded = new MemoryStream();
        image.SaveAsPng(encoded);
        var png = encoded.ToArray();

        // Insert a bounded envelope before IEND. Its type is invalid even when
        // its opaque payload happens to contain familiar frame-control names.
        byte[] payload = "fcTLfdAT"u8.ToArray();
        var chunk = new byte[12 + payload.Length];
        BinaryPrimitives.WriteUInt32BigEndian(chunk, (uint)payload.Length);
        chunk[4] = invalidType;
        chunk[5] = (byte)'B';
        chunk[6] = (byte)'A';
        chunk[7] = (byte)'D';
        payload.CopyTo(chunk, 8);

        using var input = new MemoryStream();
        input.Write(png.AsSpan(0, png.Length - 12));
        input.Write(chunk);
        input.Write(png.AsSpan(png.Length - 12));
        input.Position = 0;

        var policy = typeof(FileStorageService).Assembly.GetType(
            "BlogApp.Infrastructure.Services.Helpers.ImageProcessingSecurity", throwOnError: true)!;
        var count = policy.GetMethod("CountPngFrames", BindingFlags.NonPublic | BindingFlags.Static)!;
        var rejected = Assert.Throws<TargetInvocationException>(() =>
            count.Invoke(null, [input, CancellationToken.None]));
        Assert.IsType<ValidationException>(rejected.InnerException);
    }
}
