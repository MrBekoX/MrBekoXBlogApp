using System.Buffers;
using System.Buffers.Binary;
using System.Reflection;
using System.Text;
using BlogApp.Core.Application.Common.Interfaces.Services;
using BlogApp.Core.Domain.Exceptions;
using BlogApp.Infrastructure.Services;
using Microsoft.Extensions.FileProviders;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Logging.Abstractions;
using SixLabors.ImageSharp;
using SixLabors.ImageSharp.Formats;
using SixLabors.ImageSharp.Formats.Gif;
using SixLabors.ImageSharp.Formats.Jpeg;
using SixLabors.ImageSharp.Formats.Png;
using SixLabors.ImageSharp.Formats.Webp;
using SixLabors.ImageSharp.Memory;
using SixLabors.ImageSharp.Metadata.Profiles.Exif;
using SixLabors.ImageSharp.Metadata.Profiles.Icc;
using SixLabors.ImageSharp.Metadata.Profiles.Xmp;
using SixLabors.ImageSharp.PixelFormats;
using Xunit;

namespace BlogApp.Presentation.Api.Tests.Media;

public sealed class ImageProcessingSecurityTests
{
    private const long MaximumInputBytes = 10 * 1024 * 1024;

    [Theory]
    [InlineData(".jpg", "image/jpeg", false)]
    [InlineData(".png", "image/png", false)]
    [InlineData(".gif", "image/gif", false)]
    [InlineData(".webp", "image/webp", false)]
    [InlineData(".jpg", "image/jpeg", true)]
    [InlineData(".png", "image/png", true)]
    [InlineData(".gif", "image/gif", true)]
    [InlineData(".webp", "image/webp", true)]
    public async Task SupportedFormats_PreserveOutputAndThumbnailContracts(
        string extension, string originalContentType, bool convertToWebp)
    {
        using var fixture = new StorageFixture();
        using var source = new MemoryStream(CreateStill(extension));

        var result = await fixture.Service.UploadImageAsync(source, "picture" + extension,
            new ImageUploadOptions { ConvertToWebP = convertToWebp });

        Assert.Equal(64, result.Width);
        Assert.Equal(32, result.Height);
        Assert.Equal(convertToWebp ? "image/webp" : originalContentType, result.ContentType);
        Assert.EndsWith(convertToWebp ? ".webp" : extension, result.Url);
        var path = fixture.PathFor(result.Url);
        Assert.Equal(new FileInfo(path).Length, result.FileSize);
        using var output = Image.Load(path);
        Assert.Equal(new Size(64, 32), output.Size);
        Assert.Equal(FormatName(convertToWebp ? ".webp" : extension),
            Image.DetectFormat(path).Name.ToLowerInvariant());
        Assert.NotNull(result.ThumbnailUrl);
        using var thumbnail = Image.Load(fixture.PathFor(result.ThumbnailUrl!));
        Assert.Equal(new Size(400, 300), thumbnail.Size);
        Assert.EndsWith(convertToWebp ? ".webp" : ".jpg", result.ThumbnailUrl!);
    }

    [Fact]
    public async Task Resize_PreservesAspectRatioBeforeCreatingCropThumbnail()
    {
        using var fixture = new StorageFixture();
        using var image = new Image<Rgba32>(800, 400, Color.CornflowerBlue.ToPixel<Rgba32>());
        using var source = Encode(image, new PngEncoder());

        var result = await fixture.Service.UploadImageAsync(source, "wide.png",
            new ImageUploadOptions { MaxWidth = 200, MaxHeight = 200 });

        Assert.Equal(200, result.Width);
        Assert.Equal(100, result.Height);
        using var thumbnail = Image.Load(fixture.PathFor(result.ThumbnailUrl!));
        Assert.Equal(new Size(400, 300), thumbnail.Size);
    }

    [Fact]
    public async Task OriginalSixteenBitPng_RetainsPrecisionAndAlpha()
    {
        using var fixture = new StorageFixture();
        var pixel = new Rgba64(1001, 2002, 3003, 4004);
        using var image = new Image<Rgba64>(8, 6, pixel);
        using var source = Encode(image,
            new PngEncoder { BitDepth = PngBitDepth.Bit16, ColorType = PngColorType.RgbWithAlpha });

        var result = await fixture.Service.UploadImageAsync(source, "precision.png",
            new ImageUploadOptions { ConvertToWebP = false, GenerateThumbnail = false });

        using var output = Image.Load<Rgba64>(fixture.PathFor(result.Url));
        Assert.Equal(PngBitDepth.Bit16, output.Metadata.GetPngMetadata().BitDepth);
        Assert.Equal(pixel, output[0, 0]);
        Assert.Null(result.ThumbnailUrl);
    }

    [Theory]
    [InlineData(".png")]
    [InlineData(".webp")]
    public async Task TransparentInputs_RetainAlphaWhenConvertedToWebp(string extension)
    {
        using var fixture = new StorageFixture();
        using var image = new Image<Rgba32>(16, 16, new Rgba32(20, 40, 80, 255));
        image[0, 0] = new Rgba32(255, 0, 0, 0);
        image[1, 0] = new Rgba32(0, 255, 0, 128);
        using var source = Encode(image, EncoderFor(extension));

        var result = await fixture.Service.UploadImageAsync(source, "alpha" + extension,
            new ImageUploadOptions { GenerateThumbnail = false });

        using var output = Image.Load<Rgba32>(fixture.PathFor(result.Url));
        Assert.Equal((byte)0, output[0, 0].A);
        Assert.Equal((byte)128, output[1, 0].A);
        Assert.Equal((byte)255, output[15, 15].A);
    }

    [Theory]
    [InlineData(".gif", false)]
    [InlineData(".png", false)]
    [InlineData(".webp", false)]
    [InlineData(".gif", true)]
    [InlineData(".png", true)]
    [InlineData(".webp", true)]
    public async Task AnimatedInputs_PreserveAllFramesAndDurations(string extension, bool convertToWebp)
    {
        using var fixture = new StorageFixture();
        using var source = new MemoryStream(CreateAnimation(extension, 3));

        var result = await fixture.Service.UploadImageAsync(source, "animation" + extension,
            new ImageUploadOptions { ConvertToWebP = convertToWebp });

        using var output = Image.Load(fixture.PathFor(result.Url));
        Assert.Equal(3, output.Frames.Count);
        var outputExtension = convertToWebp ? ".webp" : extension;
        Assert.Equal(new double[] { 100, 200, 300 }, FrameDurations(output, outputExtension));
        if (convertToWebp)
        {
            Assert.Equal((ushort)0, output.Metadata.GetWebpMetadata().RepeatCount);
            using var thumbnail = Image.Load(fixture.PathFor(result.ThumbnailUrl!));
            Assert.Equal(3, thumbnail.Frames.Count);
            Assert.Equal(new double[] { 100, 200, 300 }, FrameDurations(thumbnail, ".webp"));
        }
    }

    [Theory]
    [InlineData(".gif")]
    [InlineData(".png")]
    [InlineData(".webp")]
    public async Task FrameLimit_AcceptsOneHundredFramesWithoutTruncation(string extension)
    {
        using var fixture = new StorageFixture();
        using var source = new MemoryStream(CreateAnimation(extension, 100));

        var result = await fixture.Service.UploadImageAsync(source, "allowed" + extension,
            new ImageUploadOptions { GenerateThumbnail = false });

        using var output = Image.Load(fixture.PathFor(result.Url));
        Assert.Equal(100, output.Frames.Count);
    }

    [Theory]
    [InlineData(".gif")]
    [InlineData(".png")]
    [InlineData(".webp")]
    public async Task FrameLimit_RejectsOneHundredAndOneRealFrames(string extension)
    {
        using var fixture = new StorageFixture();
        // All frames are encoder-generated. A forged APNG acTL count alone is not evidence of frame limiting.
        using var source = new MemoryStream(CreateAnimation(extension, 101));

        var error = await Assert.ThrowsAsync<ValidationException>(() =>
            fixture.Service.UploadImageAsync(source, "too-many" + extension));

        Assert.Contains("File", error.Errors.Keys);
        fixture.AssertNoImages();
    }

    [Theory]
    [InlineData(true, 3)]
    [InlineData(false, 3)]
    [InlineData(false, 100)]
    [InlineData(false, 101)]
    public async Task ApngRootParticipation_CountsTheStoredDefaultFrame(bool animateRootFrame, int storedFrames)
    {
        using var fixture = new StorageFixture();
        using var source = new MemoryStream(CreateAnimation(".png", storedFrames, animateRootFrame));
        if (storedFrames > 100)
        {
            var error = await Assert.ThrowsAsync<ValidationException>(() =>
                fixture.Service.UploadImageAsync(source, "default-frame.png",
                    new ImageUploadOptions { GenerateThumbnail = false }));
            Assert.Contains("File", error.Errors.Keys);
            fixture.AssertNoImages();
            return;
        }

        var result = await fixture.Service.UploadImageAsync(source, "default-frame.png",
            new ImageUploadOptions { GenerateThumbnail = false });

        using var output = Image.Load(fixture.PathFor(result.Url));
        Assert.Equal(storedFrames, output.Frames.Count);
    }

    [Fact]
    public async Task ApngDeclaredFrameCount_MustMatchTheRealFrameControls()
    {
        using var fixture = new StorageFixture();
        var bytes = CreateAnimation(".png", 3);
        for (var offset = 8; offset + 12 <= bytes.Length;)
        {
            var length = (int)BinaryPrimitives.ReadUInt32BigEndian(bytes.AsSpan(offset, 4));
            if (bytes.AsSpan(offset + 4, 4).SequenceEqual("acTL"u8))
            {
                BinaryPrimitives.WriteUInt32BigEndian(bytes.AsSpan(offset + 8, 4), 4);
                BinaryPrimitives.WriteUInt32BigEndian(bytes.AsSpan(offset + 8 + length, 4),
                    PngCrc32(bytes.AsSpan(offset + 4, length + 4)));
                break;
            }
            offset += length + 12;
        }
        using var source = new MemoryStream(bytes);

        var error = await Assert.ThrowsAsync<ValidationException>(() =>
            fixture.Service.UploadImageAsync(source, "count-mismatch.png"));

        Assert.Contains("File", error.Errors.Keys);
        fixture.AssertNoImages();
    }

    [Fact]
    public async Task AnimatedWebp_RejectsUnsupportedOrderingWithoutReturningTruncatedImage()
    {
        using var fixture = new StorageFixture();
        using var source = new MemoryStream(InterleaveWebpXmp(CreateAnimation(".webp", 3, includeXmp: true)));

        var error = await Assert.ThrowsAsync<ValidationException>(() =>
            fixture.Service.UploadImageAsync(source, "interleaved.webp",
                new ImageUploadOptions { GenerateThumbnail = false }));

        Assert.Contains("File", error.Errors.Keys);
        fixture.AssertNoImages();
    }

    [Fact]
    public async Task WebpDeclaredContainerEnd_MustCoverAllActualFrameBytes()
    {
        using var fixture = new StorageFixture();
        var bytes = CreateAnimation(".webp", 3);
        var offset = 12;
        while (!bytes.AsSpan(offset, 4).SequenceEqual("ANMF"u8))
        {
            var length = (int)BinaryPrimitives.ReadUInt32LittleEndian(bytes.AsSpan(offset + 4, 4));
            offset += 8 + length + (length & 1);
        }
        var firstFrameLength = (int)BinaryPrimitives.ReadUInt32LittleEndian(bytes.AsSpan(offset + 4, 4));
        var declaredEnd = offset + 8 + firstFrameLength + (firstFrameLength & 1);
        BinaryPrimitives.WriteUInt32LittleEndian(bytes.AsSpan(4, 4), (uint)(declaredEnd - 8));
        using var source = new MemoryStream(bytes);

        var error = await Assert.ThrowsAsync<ValidationException>(() =>
            fixture.Service.UploadImageAsync(source, "trailing-frames.webp"));

        Assert.Contains("File", error.Errors.Keys);
        fixture.AssertNoImages();
    }

    [Fact]
    public async Task WebpFrames_HiddenInsideUnknownOuterChunk_AreRejected()
    {
        using var fixture = new StorageFixture();
        var chunks = ReadWebpChunks(CreateAnimation(".webp", 3));
        var firstFrame = chunks.FindIndex(chunk => chunk.AsSpan(0, 4).SequenceEqual("ANMF"u8));
        var nestedFrames = chunks.Where(chunk => chunk.AsSpan(0, 4).SequenceEqual("ANMF"u8))
            .SelectMany(chunk => chunk).ToArray();
        chunks.RemoveAll(chunk => chunk.AsSpan(0, 4).SequenceEqual("ANMF"u8));
        chunks.Insert(firstFrame, WebpChunk("JUNK", nestedFrames));
        using var source = new MemoryStream(RebuildWebp(chunks));

        var error = await Assert.ThrowsAsync<ValidationException>(() =>
            fixture.Service.UploadImageAsync(source, "hidden-frames.webp"));

        Assert.Contains("File", error.Errors.Keys);
        fixture.AssertNoImages();
    }

    [Fact]
    public async Task WebpFramePayload_WithAdditionalNestedFrameChunk_IsRejected()
    {
        using var fixture = new StorageFixture();
        var chunks = ReadWebpChunks(CreateAnimation(".webp", 3));
        var frames = chunks.Where(chunk => chunk.AsSpan(0, 4).SequenceEqual("ANMF"u8)).ToArray();
        Assert.Equal(3, frames.Length);
        var firstLength = (int)BinaryPrimitives.ReadUInt32LittleEndian(frames[0].AsSpan(4, 4));
        var firstPayload = frames[0].AsSpan(8, firstLength).ToArray();
        var nestedPayload = firstPayload.Concat(frames[1]).ToArray();
        chunks[chunks.IndexOf(frames[0])] = WebpChunk("ANMF", nestedPayload);
        using var source = new MemoryStream(RebuildWebp(chunks));

        var error = await Assert.ThrowsAsync<ValidationException>(() =>
            fixture.Service.UploadImageAsync(source, "nested-frame.webp"));

        Assert.Contains("File", error.Errors.Keys);
        fixture.AssertNoImages();
    }

    [Fact]
    public async Task CrcValidPng_WithInvalidCompressedData_ProducesDomainValidation()
    {
        using var fixture = new StorageFixture();
        var bytes = CreateStill(".png");
        var changed = false;
        for (var offset = 8; offset + 12 <= bytes.Length;)
        {
            var length = (int)BinaryPrimitives.ReadUInt32BigEndian(bytes.AsSpan(offset, 4));
            if (bytes.AsSpan(offset + 4, 4).SequenceEqual("IDAT"u8))
            {
                Assert.True(length >= 2);
                bytes[offset + 8] = bytes[offset + 9] = 0xff;
                BinaryPrimitives.WriteUInt32BigEndian(bytes.AsSpan(offset + 8 + length, 4),
                    PngCrc32(bytes.AsSpan(offset + 4, length + 4)));
                changed = true;
                break;
            }
            offset += length + 12;
        }
        Assert.True(changed);
        using var source = new MemoryStream(bytes);

        var error = await Assert.ThrowsAsync<ValidationException>(() =>
            fixture.Service.UploadImageAsync(source, "invalid-compression.png"));

        Assert.Contains("File", error.Errors.Keys);
        fixture.AssertNoImages();
    }

    [Theory]
    [InlineData(16385, 1)]
    [InlineData(1, 16385)]
    [InlineData(4096, 3073)]
    public async Task CanvasLimits_RejectValidOversizedImagesBeforeSaving(int width, int height)
    {
        using var fixture = new StorageFixture();
        byte[] encoded;
        using (var image = new Image<Rgba32>(width, height))
        using (var buffer = Encode(image, new PngEncoder()))
            encoded = buffer.ToArray();
        using var source = new MemoryStream(encoded);

        var error = await Assert.ThrowsAsync<ValidationException>(() =>
            fixture.Service.UploadImageAsync(source, "oversized.png",
                new ImageUploadOptions { GenerateThumbnail = false }));

        Assert.Contains("File", error.Errors.Keys);
        fixture.AssertNoImages();
    }

    [Fact]
    public async Task AnimatedPixelBudget_AppliesAcrossOtherwiseAllowedFrames()
    {
        using var fixture = new StorageFixture();
        // Forty-nine 512-square frames exceed 12 Mi pixels while staying under every per-frame/count limit.
        using var source = new MemoryStream(CreateAnimation(".png", 49, width: 512, height: 512));

        var error = await Assert.ThrowsAsync<ValidationException>(() =>
            fixture.Service.UploadImageAsync(source, "aggregate.png",
                new ImageUploadOptions { GenerateThumbnail = false }));

        Assert.Contains("File", error.Errors.Keys);
        fixture.AssertNoImages();
    }

    [Fact]
    public async Task CombinedOutputBudget_IncludesMainImageAndEveryThumbnailFrame()
    {
        using var fixture = new StorageFixture();
        using var source = new MemoryStream(CreateAnimation(".png", 3));

        var error = await Assert.ThrowsAsync<ValidationException>(() =>
            fixture.Service.UploadImageAsync(source, "combined.png", new ImageUploadOptions
            {
                ThumbnailWidth = 2048, ThumbnailHeight = 2048
            }));

        // The thumbnail alone is exactly 12 Mi pixels; the three main frames exceed the combined budget.
        Assert.Contains("Options", error.Errors.Keys);
        fixture.AssertNoImages();
    }

    [Fact]
    public void ActiveBufferAccounting_EnforcesLiveBudgetAndReleasesReservations()
    {
        const int mib = 1024 * 1024;
        var inner = new TrackingAllocator();
        var type = typeof(FileStorageService).Assembly.GetType(
            "BlogApp.Infrastructure.Services.Helpers.ImageProcessingSecurity+AccountingMemoryAllocator", throwOnError: true)!;
        var allocator = (MemoryAllocator)Activator.CreateInstance(type,
            BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic, binder: null,
            args: [inner], culture: null)!;
        var first = allocator.Allocate<byte>(80 * mib);

        Assert.Throws<InvalidMemoryOperationException>(() => allocator.Allocate<byte>(49 * mib));
        Assert.Equal(1, inner.SuccessfulAllocations);
        first.Dispose();
        first.Dispose();
        Assert.Equal(1, inner.ReleasedAllocations);
        using (var fullBudget = allocator.Allocate<byte>(128 * mib))
            Assert.Throws<InvalidMemoryOperationException>(() => allocator.Allocate<byte>(1));

        // A failed backing allocation must release its reservation before the next request.
        inner.FailNextAllocation = true;
        Assert.Throws<InvalidMemoryOperationException>(() => allocator.Allocate<byte>(80 * mib));
        using var recovered = allocator.Allocate<byte>(128 * mib);
        Assert.Equal(3, inner.SuccessfulAllocations);
    }

    [Theory]
    [InlineData(false, false)]
    [InlineData(true, false)]
    [InlineData(false, true)]
    [InlineData(true, true)]
    public async Task TiffSignatures_AreRejectedEvenWithPngFilename(bool bigEndian, bool bigTiff)
    {
        using var fixture = new StorageFixture();
        // Harmless signatures only: no TIFF decoder, encoder, IFD entries or advisory trigger is executed.
        var header = new byte[16];
        header[0] = header[1] = bigEndian ? (byte)'M' : (byte)'I';
        header[bigEndian ? 3 : 2] = bigTiff ? (byte)43 : (byte)42;
        using var source = new MemoryStream(header);

        var error = await Assert.ThrowsAsync<ValidationException>(() =>
            fixture.Service.UploadImageAsync(source, "forged.png"));

        Assert.Contains("File", error.Errors.Keys);
        fixture.AssertNoImages();
    }

    [Theory]
    [InlineData("broken.png")]
    [InlineData("broken.jpg")]
    [InlineData("broken.gif")]
    [InlineData("broken.webp")]
    [InlineData("broken.tiff")]
    public async Task MalformedOrUnsupportedInputs_ProduceDomainValidation(string filename)
    {
        using var fixture = new StorageFixture();
        using var source = new MemoryStream([1, 2, 3, 4, 5]);

        var error = await Assert.ThrowsAsync<ValidationException>(() =>
            fixture.Service.UploadImageAsync(source, filename));

        Assert.Contains("File", error.Errors.Keys);
        fixture.AssertNoImages();
    }

    [Fact]
    public async Task ActualInputLimit_BoundsAStreamWithDishonestLength()
    {
        using var fixture = new StorageFixture();
        using var source = new CountingReadStream(MaximumInputBytes + 1024);

        var error = await Assert.ThrowsAsync<ValidationException>(() =>
            fixture.Service.UploadImageAsync(source, "oversized.png"));

        Assert.Contains("File", error.Errors.Keys);
        Assert.Equal(MaximumInputBytes + 1, source.BytesRead);
        fixture.AssertNoImages();
    }

    [Theory]
    [InlineData("quality-low")]
    [InlineData("quality-high")]
    [InlineData("width")]
    [InlineData("height")]
    [InlineData("thumbnail-width")]
    [InlineData("thumbnail-height")]
    [InlineData("output-budget")]
    public async Task InvalidOptions_AreRejectedBeforeReadingTheSource(string invalidOption)
    {
        using var fixture = new StorageFixture();
        using var source = new CountingReadStream(16);
        var options = new ImageUploadOptions();
        switch (invalidOption)
        {
            case "quality-low": options.Quality = -1; break;
            case "quality-high": options.Quality = 101; break;
            case "width": options.MaxWidth = 0; break;
            case "height": options.MaxHeight = 0; break;
            case "thumbnail-width": options.ThumbnailWidth = 0; break;
            case "thumbnail-height": options.ThumbnailHeight = 0; break;
            case "output-budget": options.ThumbnailWidth = options.ThumbnailHeight = 4096; break;
        }

        var error = await Assert.ThrowsAsync<ValidationException>(() =>
            fixture.Service.UploadImageAsync(source, "valid.png", options));

        Assert.Contains("Options", error.Errors.Keys);
        Assert.Equal(0, source.BytesRead);
        fixture.AssertNoImages();
    }

    [Theory]
    [InlineData(0)]
    [InlineData(100)]
    public async Task QualityEndpoints_RemainAccepted(int quality)
    {
        using var fixture = new StorageFixture();
        using var source = new MemoryStream(CreateStill(".png"));

        var result = await fixture.Service.UploadImageAsync(source, "quality.png",
            new ImageUploadOptions { Quality = quality, GenerateThumbnail = false });

        Assert.True(File.Exists(fixture.PathFor(result.Url)));
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task Metadata_IsStrippedFromSavedOutputs(bool convertToWebp)
    {
        using var fixture = new StorageFixture();
        using var image = new Image<Rgba32>(16, 16);
        image.Metadata.ExifProfile = new ExifProfile();
        image.Metadata.ExifProfile.SetValue(ExifTag.Software, "benign metadata fixture");
        image.Metadata.XmpProfile = new XmpProfile(Encoding.UTF8.GetBytes(
            "<x:xmpmeta xmlns:x=\"adobe:ns:meta/\"><rdf:RDF xmlns:rdf=\"http://www.w3.org/1999/02/22-rdf-syntax-ns#\"/></x:xmpmeta>"));
        // A benign zero-tag ICC header exercises ordinary metadata stripping, not the ICC advisory.
        image.Metadata.IccProfile = new IccProfile(CreateBenignIccHeader());
        using var source = Encode(image, new PngEncoder());
        using (var baseline = Image.Load(source.ToArray()))
        {
            Assert.NotNull(baseline.Metadata.ExifProfile);
            Assert.NotNull(baseline.Metadata.XmpProfile);
            Assert.NotNull(baseline.Metadata.IccProfile);
        }

        var result = await fixture.Service.UploadImageAsync(source, "metadata.png",
            new ImageUploadOptions { ConvertToWebP = convertToWebp });

        using var output = Image.Load(fixture.PathFor(result.Url));
        using var thumbnail = Image.Load(fixture.PathFor(result.ThumbnailUrl!));
        foreach (var saved in new[] { output, thumbnail })
        {
            Assert.Null(saved.Metadata.ExifProfile);
            Assert.Null(saved.Metadata.XmpProfile);
            Assert.Null(saved.Metadata.IccProfile);
            Assert.Null(saved.Metadata.IptcProfile);
        }
    }

    [Theory]
    [InlineData(".jpg")]
    [InlineData(".png")]
    [InlineData(".webp")]
    public async Task PublicAdvisoryIccFixture_IsNeverParsedAndIsRemovedFromOutput(string extension)
    {
        using var fixture = new StorageFixture();
        using var image = new Image<Rgba32>(8, 6, new Rgba32(40, 80, 120));
        var rawProfile = CreatePublicAdvisoryIccProfile();
        Assert.Equal(200, rawProfile.Length);
        image.Metadata.IccProfile = new IccProfile(rawProfile);
        // Raw construction and serialization do not access Entries. Never run a vulnerable parser baseline.
        using var source = Encode(image, EncoderFor(extension));

        var allocatedBefore = GC.GetTotalAllocatedBytes(precise: true);
        var result = await fixture.Service.UploadImageAsync(source, "public-profile" + extension);
        var allocated = GC.GetTotalAllocatedBytes(precise: true) - allocatedBefore;

        // The v3 CLUT Entries regression allocates about 115 MB from this tiny
        // profile. Check the real protected path, not only its final metadata.
        Assert.InRange(allocated, 0, 64L * 1024 * 1024);

        using var output = Image.Load(fixture.PathFor(result.Url));
        using var thumbnail = Image.Load(fixture.PathFor(result.ThumbnailUrl!));
        Assert.Equal(new Size(8, 6), output.Size);
        Assert.Null(output.Metadata.IccProfile);
        Assert.Null(thumbnail.Metadata.IccProfile);
    }

    [Fact]
    public async Task Processing_DoesNotMutateGlobalImageSharpConfiguration()
    {
        var configuration = Configuration.Default;
        var formats = configuration.ImageFormats.ToArray();
        var allocator = configuration.MemoryAllocator;
        var parallelism = configuration.MaxDegreeOfParallelism;
        using var fixture = new StorageFixture();
        using var source = new MemoryStream(CreateStill(".png"));

        await fixture.Service.UploadImageAsync(source, "isolated.png",
            new ImageUploadOptions { GenerateThumbnail = false });

        Assert.Same(configuration, Configuration.Default);
        Assert.Same(allocator, configuration.MemoryAllocator);
        Assert.Equal(parallelism, configuration.MaxDegreeOfParallelism);
        Assert.Equal(formats, configuration.ImageFormats.ToArray());
    }

    [Fact]
    public async Task IoFailures_AreNotConvertedToValidationAndReleaseAdmission()
    {
        using var fixture = new StorageFixture();
        using var failed = new ThrowingReadStream();

        await Assert.ThrowsAsync<IOException>(() => fixture.Service.UploadImageAsync(failed, "failed.png"));
        fixture.AssertNoImages();
        using var valid = new MemoryStream(CreateStill(".png"));
        var result = await fixture.Service.UploadImageAsync(valid, "recovery.png",
            new ImageUploadOptions { GenerateThumbnail = false });
        Assert.True(File.Exists(fixture.PathFor(result.Url)));
    }

    [Fact]
    public async Task ProcessAdmission_IsSharedAcrossServiceInstancesAndCancellableBeforeReading()
    {
        using var first = new StorageFixture();
        using var second = new StorageFixture();
        using var blocked = new BlockingReadStream(CreateStill(".png"));
        using var waiting = new CountingReadStream(16);
        using var cancellation = new CancellationTokenSource();
        var active = first.Service.UploadImageAsync(blocked, "active.png",
            new ImageUploadOptions { GenerateThumbnail = false });
        try
        {
            await blocked.ReadStarted.Task.WaitAsync(TimeSpan.FromSeconds(5));
            var queued = second.Service.UploadImageAsync(waiting, "waiting.png",
                cancellationToken: cancellation.Token);
            cancellation.Cancel();

            await Assert.ThrowsAnyAsync<OperationCanceledException>(() => queued);
            Assert.Equal(0, waiting.BytesRead);
            second.AssertNoImages();
        }
        finally
        {
            blocked.Release.TrySetResult();
            await active;
        }
    }

    [Fact]
    public async Task CancellationAfterSaving_RemovesMainAndThumbnailAndReleasesAdmission()
    {
        using var cancellation = new CancellationTokenSource();
        var logger = new CancelAfterUploadLogger(cancellation);
        using var fixture = new StorageFixture(logger);
        using var source = new MemoryStream(CreateStill(".png"));

        await Assert.ThrowsAnyAsync<OperationCanceledException>(() =>
            fixture.Service.UploadImageAsync(source, "cancel-after-save.png", cancellationToken: cancellation.Token));

        Assert.True(logger.UploadWasLogged);
        fixture.AssertNoImages();
        using var recovery = new MemoryStream(CreateStill(".png"));
        var result = await fixture.Service.UploadImageAsync(recovery, "after-cancel.png",
            new ImageUploadOptions { GenerateThumbnail = false });
        Assert.True(File.Exists(fixture.PathFor(result.Url)));
    }

    private static string FormatName(string extension) => extension == ".jpg" ? "jpeg" : extension[1..];

    private static IImageEncoder EncoderFor(string extension) => extension switch
    {
        ".jpg" => new JpegEncoder(),
        ".png" => new PngEncoder(),
        ".gif" => new GifEncoder(),
        ".webp" => new WebpEncoder { FileFormat = WebpFileFormatType.Lossless },
        _ => throw new ArgumentOutOfRangeException(nameof(extension))
    };

    private static MemoryStream Encode(Image image, IImageEncoder encoder)
    {
        var stream = new MemoryStream();
        image.Save(stream, encoder);
        stream.Position = 0;
        return stream;
    }

    private static byte[] CreateStill(string extension)
    {
        using var image = new Image<Rgba32>(64, 32, new Rgba32(30, 100, 180, 255));
        using var stream = Encode(image, EncoderFor(extension));
        return stream.ToArray();
    }

    private static byte[] CreateAnimation(string extension, int frameCount,
        bool animateRootFrame = true, bool includeXmp = false, int width = 4, int height = 4)
    {
        using var image = new Image<Rgba32>(width, height, new Rgba32(200, 20, 10));
        for (var index = 1; index < frameCount; index++)
        {
            using var next = new Image<Rgba32>(width, height,
                new Rgba32((byte)(index * 37), (byte)(index * 71), (byte)(index * 113)));
            image.Frames.AddFrame(next.Frames.RootFrame);
        }
        image.Metadata.GetGifMetadata().RepeatCount = 0;
        image.Metadata.GetPngMetadata().RepeatCount = 0;
        image.Metadata.GetPngMetadata().AnimateRootFrame = animateRootFrame;
        image.Metadata.GetWebpMetadata().RepeatCount = 0;
        if (includeXmp)
            image.Metadata.XmpProfile = new XmpProfile(Encoding.UTF8.GetBytes(
                "<x:xmpmeta xmlns:x=\"adobe:ns:meta/\"/>"));
        for (var index = 0; index < frameCount; index++)
        {
            var delay = index % 3 + 1;
            var metadata = image.Frames[index].Metadata;
            metadata.GetGifMetadata().FrameDelay = delay * 10;
            metadata.GetPngMetadata().FrameDelay = new Rational((uint)delay, 10);
            metadata.GetWebpMetadata().FrameDelay = (uint)(delay * 100);
        }
        using var stream = Encode(image, EncoderFor(extension));
        return stream.ToArray();
    }

    private static byte[] InterleaveWebpXmp(byte[] bytes)
    {
        var chunks = ReadWebpChunks(bytes);
        var metadata = Assert.Single(chunks, chunk => chunk.AsSpan(0, 4).SequenceEqual("XMP "u8));
        chunks.Remove(metadata);
        var firstFrame = chunks.FindIndex(chunk => chunk.AsSpan(0, 4).SequenceEqual("ANMF"u8));
        Assert.True(firstFrame >= 0);
        chunks.Insert(firstFrame + 1, metadata);
        using var reordered = new MemoryStream();
        reordered.Write(bytes.AsSpan(0, 12));
        foreach (var chunk in chunks) reordered.Write(chunk);
        return reordered.ToArray();
    }

    private static List<byte[]> ReadWebpChunks(byte[] bytes)
    {
        var chunks = new List<byte[]>();
        for (var offset = 12; offset + 8 <= bytes.Length;)
        {
            var length = (int)BinaryPrimitives.ReadUInt32LittleEndian(bytes.AsSpan(offset + 4, 4));
            var total = 8 + length + (length & 1);
            chunks.Add(bytes.AsSpan(offset, total).ToArray());
            offset += total;
        }
        return chunks;
    }

    private static byte[] WebpChunk(string tag, byte[] payload)
    {
        var bytes = new byte[8 + payload.Length + (payload.Length & 1)];
        Encoding.ASCII.GetBytes(tag).CopyTo(bytes, 0);
        BinaryPrimitives.WriteUInt32LittleEndian(bytes.AsSpan(4, 4), (uint)payload.Length);
        payload.CopyTo(bytes, 8);
        return bytes;
    }

    private static byte[] RebuildWebp(IEnumerable<byte[]> chunks)
    {
        using var output = new MemoryStream();
        output.Write("RIFF\0\0\0\0WEBP"u8);
        foreach (var chunk in chunks) output.Write(chunk);
        var bytes = output.ToArray();
        BinaryPrimitives.WriteUInt32LittleEndian(bytes.AsSpan(4, 4), (uint)(bytes.Length - 8));
        return bytes;
    }

    private static uint PngCrc32(ReadOnlySpan<byte> bytes)
    {
        var crc = uint.MaxValue;
        foreach (var value in bytes)
        {
            crc ^= value;
            for (var bit = 0; bit < 8; bit++)
                crc = (crc >> 1) ^ ((crc & 1) == 0 ? 0 : 0xedb88320u);
        }
        return ~crc;
    }

    private static double[] FrameDurations(Image image, string extension) =>
        image.Frames.Select(frame => extension switch
        {
            ".gif" => frame.Metadata.GetGifMetadata().FrameDelay * 10d,
            ".png" => frame.Metadata.GetPngMetadata().FrameDelay.ToDouble() * 1000,
            ".webp" => frame.Metadata.GetWebpMetadata().FrameDelay,
            _ => throw new ArgumentOutOfRangeException(nameof(extension))
        }).ToArray();

    private static byte[] CreateBenignIccHeader()
    {
        var data = new byte[132];
        BinaryPrimitives.WriteUInt32BigEndian(data, (uint)data.Length);
        Encoding.ASCII.GetBytes("mntr").CopyTo(data, 12);
        Encoding.ASCII.GetBytes("RGB ").CopyTo(data, 16);
        Encoding.ASCII.GetBytes("XYZ ").CopyTo(data, 20);
        Encoding.ASCII.GetBytes("acsp").CopyTo(data, 36);
        return data;
    }

    private static byte[] CreatePublicAdvisoryIccProfile()
    {
        // Exact 200-byte fixture described by BuildTruncatedProfile, lines 224-250:
        // https://github.com/advisories/GHSA-gwg2-r3hj-4w44
        var bytes = new byte[200];
        void Write32(int offset, uint value) => BinaryPrimitives.WriteUInt32BigEndian(bytes.AsSpan(offset, 4), value);
        void Write16(int offset, ushort value) => BinaryPrimitives.WriteUInt16BigEndian(bytes.AsSpan(offset, 2), value);
        Write32(0, 200);
        Encoding.ASCII.GetBytes("test").CopyTo(bytes, 4);
        Write32(8, 0x04000000);
        Write32(12, 0x6d6e7472);
        Write32(16, 0x52474220);
        Write32(20, 0x58595a20);
        Encoding.ASCII.GetBytes("acsp").CopyTo(bytes, 36);
        Write32(128, 1);
        Write32(132, 0x41324230);
        Write32(136, 144);
        Write32(140, 56);
        Write32(144, 0x6d706574);
        Write16(152, 0);
        Write16(154, 0);
        Write32(156, 1);
        Write32(160, 24);
        Write32(164, 32);
        Write32(168, 0x636c7574);
        Write16(172, 15);
        Write16(174, 15);
        bytes.AsSpan(176, 15).Fill(3);
        return bytes;
    }

    private sealed class StorageFixture : IDisposable
    {
        private readonly string root = Path.Combine(AppContext.BaseDirectory, "image-security-tests", Guid.NewGuid().ToString("N"));
        public FileStorageService Service { get; }
        public StorageFixture(ILogger<FileStorageService>? logger = null) =>
            Service = new FileStorageService(new TestEnvironment(root), logger ?? NullLogger<FileStorageService>.Instance);
        public string PathFor(string url) => Path.Combine(root, url.TrimStart('/').Replace('/', Path.DirectorySeparatorChar));
        public void AssertNoImages() => Assert.Empty(Directory.EnumerateFiles(root, "*", SearchOption.AllDirectories));
        public void Dispose() { if (Directory.Exists(root)) Directory.Delete(root, recursive: true); }
    }

    private sealed class TestEnvironment(string root) : IHostEnvironment
    {
        public string EnvironmentName { get; set; } = "Testing";
        public string ApplicationName { get; set; } = nameof(ImageProcessingSecurityTests);
        public string ContentRootPath { get; set; } = root;
        public IFileProvider ContentRootFileProvider { get; set; } = new NullFileProvider();
    }

    private sealed class CancelAfterUploadLogger(CancellationTokenSource cancellation) : ILogger<FileStorageService>
    {
        public bool UploadWasLogged { get; private set; }
        public IDisposable? BeginScope<TState>(TState state) where TState : notnull => null;
        public bool IsEnabled(LogLevel logLevel) => true;
        public void Log<TState>(LogLevel logLevel, EventId eventId, TState state, Exception? exception,
            Func<TState, Exception?, string> formatter)
        {
            if (!formatter(state, exception).StartsWith("Image uploaded:", StringComparison.Ordinal)) return;
            UploadWasLogged = true;
            cancellation.Cancel();
        }
    }

    private sealed class TrackingAllocator : MemoryAllocator
    {
        public bool FailNextAllocation { get; set; }
        public int SuccessfulAllocations { get; private set; }
        public int ReleasedAllocations { get; private set; }
        protected override int GetBufferCapacityInBytes() => 4 * 1024 * 1024;
        public override IMemoryOwner<T> Allocate<T>(int length, AllocationOptions options = AllocationOptions.None)
        {
            if (FailNextAllocation)
            {
                FailNextAllocation = false;
                throw new InvalidMemoryOperationException("Intentional backing allocation failure.");
            }
            SuccessfulAllocations++;
            // Only reservation accounting is under test; no image algorithm consumes this owner.
            return new TrackingOwner<T>(() => ReleasedAllocations++);
        }
        private sealed class TrackingOwner<T>(Action release) : IMemoryOwner<T>
        {
            private bool disposed;
            public Memory<T> Memory => Memory<T>.Empty;
            public void Dispose()
            {
                if (disposed) return;
                disposed = true;
                release();
            }
        }
    }

    private class CountingReadStream(long actualLength) : Stream
    {
        public long BytesRead { get; private set; }
        public override bool CanRead => true;
        public override bool CanSeek => false;
        public override bool CanWrite => false;
        public override long Length => 1; // The security boundary must measure the actual bytes.
        public override long Position { get => BytesRead; set => throw new NotSupportedException(); }
        public override int Read(byte[] buffer, int offset, int count) => Read(buffer.AsSpan(offset, count));
        public override int Read(Span<byte> buffer)
        {
            var count = (int)Math.Min(buffer.Length, actualLength - BytesRead);
            buffer[..count].Clear();
            BytesRead += count;
            return count;
        }
        public override ValueTask<int> ReadAsync(Memory<byte> buffer, CancellationToken cancellationToken = default)
        {
            cancellationToken.ThrowIfCancellationRequested();
            return ValueTask.FromResult(Read(buffer.Span));
        }
        public override void Flush() => throw new NotSupportedException();
        public override long Seek(long offset, SeekOrigin origin) => throw new NotSupportedException();
        public override void SetLength(long value) => throw new NotSupportedException();
        public override void Write(byte[] buffer, int offset, int count) => throw new NotSupportedException();
    }

    private sealed class ThrowingReadStream() : CountingReadStream(1)
    {
        public override ValueTask<int> ReadAsync(Memory<byte> buffer, CancellationToken cancellationToken = default) =>
            ValueTask.FromException<int>(new IOException("Intentional source read failure."));
    }

    private sealed class BlockingReadStream(byte[] data) : MemoryStream(data)
    {
        public TaskCompletionSource ReadStarted { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        public TaskCompletionSource Release { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        public override async ValueTask<int> ReadAsync(Memory<byte> buffer, CancellationToken cancellationToken = default)
        {
            ReadStarted.TrySetResult();
            await Release.Task.WaitAsync(cancellationToken);
            return await base.ReadAsync(buffer, cancellationToken);
        }
    }
}
