using System.Buffers;
using System.Buffers.Binary;
using System.Runtime.CompilerServices;
using BlogApp.Core.Application.Common.Interfaces.Services;
using BlogApp.Core.Domain.Exceptions;
using SixLabors.ImageSharp;
using SixLabors.ImageSharp.Formats;
using SixLabors.ImageSharp.Formats.Gif;
using SixLabors.ImageSharp.Formats.Jpeg;
using SixLabors.ImageSharp.Formats.Png;
using SixLabors.ImageSharp.Formats.Webp;
using SixLabors.ImageSharp.Memory;

namespace BlogApp.Infrastructure.Services.Helpers;

/// <summary>Limits the upload processing path without changing ImageSharp's global configuration.</summary>
internal static class ImageProcessingSecurity
{
    internal const int MaximumInputBytes = 10 * 1024 * 1024;
    internal const int MaximumDimension = 16_384;
    internal const int MaximumFrames = 100;
    internal const long MaximumCanvasPixels = 12L * 1024 * 1024;
    internal const long MaximumActiveBufferBytes = 128L * 1024 * 1024;
    private const int MaximumContainerChunks = 16_384;

    // The gate covers copying, identification, decoding, transforms and all output encoding.
    private static readonly SemaphoreSlim ProcessingGate = new(1, 1);
    private static readonly MemoryAllocator SharedAllocator = MemoryAllocator.Create(new MemoryAllocatorOptions
    {
        MaximumPoolSizeMegabytes = 8,
        AllocationLimitMegabytes = 128
    });

    internal static async Task<ProcessingSession> EnterAsync(CancellationToken cancellationToken)
    {
        await ProcessingGate.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            return new ProcessingSession();
        }
        catch
        {
            ProcessingGate.Release();
            throw;
        }
    }

    internal static ImageUploadOptions ValidateOptions(ImageUploadOptions options)
    {
        // Take a snapshot so another owner of the mutable options cannot change allocation sizes later.
        var snapshot = new ImageUploadOptions
        {
            MaxWidth = options.MaxWidth,
            MaxHeight = options.MaxHeight,
            Quality = options.Quality,
            ConvertToWebP = options.ConvertToWebP,
            GenerateThumbnail = options.GenerateThumbnail,
            ThumbnailWidth = options.ThumbnailWidth,
            ThumbnailHeight = options.ThumbnailHeight
        };

        ValidateSize(snapshot.MaxWidth, snapshot.MaxHeight, "Options");
        ValidateSize(snapshot.ThumbnailWidth, snapshot.ThumbnailHeight, "Options");
        if (snapshot.Quality is < 0 or > 100)
            throw new ValidationException("Options", "Image quality must be between 0 and 100.");

        return snapshot;
    }

    internal static async Task<MemoryStream> CopyInputAsync(Stream input, CancellationToken cancellationToken)
    {
        if (!input.CanRead)
            throw InvalidImage("The image stream must be readable.");

        var initialCapacity = 0;
        if (input.CanSeek)
        {
            var length = input.Length;
            if (length < 0 || length > MaximumInputBytes)
                throw InvalidImage("Image files must not exceed 10 MB.");
            initialCapacity = (int)length;
            input.Position = 0;
        }

        var output = new MemoryStream(initialCapacity);
        try
        {
            var buffer = new byte[64 * 1024];
            while (true)
            {
                cancellationToken.ThrowIfCancellationRequested();
                var remaining = MaximumInputBytes - (int)output.Length;
                var read = await input.ReadAsync(buffer.AsMemory(0, Math.Min(buffer.Length, remaining + 1)), cancellationToken)
                    .ConfigureAwait(false);
                cancellationToken.ThrowIfCancellationRequested();
                if (read == 0)
                    break;
                if (read > remaining)
                    throw InvalidImage("Image files must not exceed 10 MB.");
                output.Write(buffer, 0, read);
            }

            if (output.Length == 0)
                throw InvalidImage("No image was uploaded.");
            output.Position = 0;
            return output;
        }
        catch
        {
            output.Dispose();
            throw;
        }
    }

    internal static int ValidateSize(int width, int height, string property = "File")
    {
        if (width is <= 0 or > MaximumDimension || height is <= 0 or > MaximumDimension ||
            (long)width * height > MaximumCanvasPixels)
            throw new ValidationException(property, "Image dimensions exceed the supported processing limits.");

        return (int)((long)width * height);
    }

    internal static int GetAllowedFrameCount(ImageInfo info)
    {
        var pixels = ValidateSize(info.Width, info.Height);
        var allowed = (int)Math.Min(MaximumFrames, MaximumCanvasPixels / pixels);
        if (info.FrameMetadataCollection.Count > allowed)
            throw InvalidImage("The image has too many frames or decoded pixels.");
        return allowed;
    }

    internal static void ValidatePlannedPixels(int width, int height, int frames, ImageUploadOptions options)
    {
        var canvasPixels = (long)ValidateSize(width, height) * frames;
        var thumbnailPixels = options.GenerateThumbnail
            ? (long)options.ThumbnailWidth * options.ThumbnailHeight * frames
            : 0;
        if (canvasPixels + thumbnailPixels > MaximumCanvasPixels)
            throw new ValidationException("Options", "The image and planned thumbnails exceed the combined pixel budget.");
    }

    internal static void ValidateDecodedImage(Image image, int allowedFrames, ImageUploadOptions options, bool includePlannedThumbnail = true)
    {
        if (image.Frames.Count > allowedFrames)
            throw InvalidImage("The image has too many frames or decoded pixels.");

        long totalPixels = 0;
        foreach (var frame in image.Frames)
        {
            totalPixels += ValidateSize(frame.Width, frame.Height);
            if (totalPixels > MaximumCanvasPixels)
                throw InvalidImage("The image has too many decoded pixels.");
        }

        if (includePlannedThumbnail)
            ValidatePlannedPixels(image.Width, image.Height, image.Frames.Count, options);
    }

    // In 3.1.12 the animated WebP decoder counts optional chunks towards MaxFrames.
    // Count top-level ANMF chunks first, then decode without that truncation option.
    internal static int CountWebpFrames(MemoryStream input, CancellationToken cancellationToken)
    {
        var bytes = input.GetBuffer().AsSpan(0, (int)input.Length);
        if (bytes.Length < 12 || !bytes[..4].SequenceEqual("RIFF"u8) || !bytes.Slice(8, 4).SequenceEqual("WEBP"u8))
            throw InvalidImage("Invalid WebP image.");

        var end = (long)BinaryPrimitives.ReadUInt32LittleEndian(bytes.Slice(4, 4)) + 8;
        if (end < 12 || end != bytes.Length)
            throw InvalidImage("Invalid WebP container length.");

        long position = 12;
        var frames = 0;
        var chunks = 0;
        var canvasWidth = 0;
        var canvasHeight = 0;
        var hasExtendedHeader = false;
        var animationDeclared = false;
        var hasAnimation = false;
        var metadataAfterFrames = false;
        while (position < end)
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (++chunks > MaximumContainerChunks || end - position < 8)
                throw InvalidImage("Truncated WebP chunk.");
            var offset = (int)position;
            var length = BinaryPrimitives.ReadUInt32LittleEndian(bytes.Slice(offset + 4, 4));
            var next = position + 8 + length + (length & 1);
            if (next > end)
                throw InvalidImage("Truncated WebP chunk.");
            var type = bytes.Slice(offset, 4);
            var data = bytes.Slice(offset + 8, (int)length);
            if (type.SequenceEqual("VP8X"u8))
            {
                if (hasExtendedHeader || position != 12 || length != 10)
                    throw InvalidImage("Invalid extended WebP header.");
                hasExtendedHeader = true;
                animationDeclared = (data[0] & 2) != 0;
                canvasWidth = ReadUInt24(data.Slice(4, 3)) + 1;
                canvasHeight = ReadUInt24(data.Slice(7, 3)) + 1;
                ValidateSize(canvasWidth, canvasHeight);
            }
            else if (type.SequenceEqual("ANIM"u8))
            {
                if (!animationDeclared || hasAnimation || length != 6)
                    throw InvalidImage("Invalid WebP animation header.");
                hasAnimation = true;
            }
            else if (type.SequenceEqual("ANMF"u8))
            {
                if (!hasAnimation || metadataAfterFrames || ++frames > MaximumFrames)
                    throw InvalidImage("Invalid WebP animation frame count or ordering.");
                ValidateWebpFrame(data, canvasWidth, canvasHeight);
                if ((long)canvasWidth * canvasHeight * frames > MaximumCanvasPixels)
                    throw InvalidImage("The image has too many decoded pixels.");
            }
            else if (type.SequenceEqual("ICCP"u8) || type.SequenceEqual("EXIF"u8) || type.SequenceEqual("XMP "u8))
            {
                if (hasAnimation && type.SequenceEqual("ICCP"u8))
                    throw InvalidImage("WebP color profiles must precede animation data.");
                metadataAfterFrames |= hasAnimation;
            }
            else if (type.SequenceEqual("VP8 "u8) || type.SequenceEqual("VP8L"u8) || type.SequenceEqual("ALPH"u8))
            {
                if (animationDeclared || hasAnimation)
                    throw InvalidImage("Animation pixels must be inside a WebP frame.");
            }
            else
            {
                // The 3.1.12 animation decoder does not skip unknown payloads. They
                // could otherwise be interpreted as additional, uncounted ANMF chunks.
                throw InvalidImage("The WebP chunk type is not supported for upload processing.");
            }
            position = next;
        }

        if (animationDeclared != hasAnimation || (hasAnimation && frames == 0))
            throw InvalidImage("Incomplete WebP animation.");
        return Math.Max(1, frames);
    }

    private static int ReadUInt24(ReadOnlySpan<byte> bytes) => bytes[0] | (bytes[1] << 8) | (bytes[2] << 16);

    private static void ValidateWebpFrame(ReadOnlySpan<byte> data, int canvasWidth, int canvasHeight)
    {
        if (data.Length < 24)
            throw InvalidImage("Truncated WebP animation frame.");
        var x = ReadUInt24(data[..3]) * 2;
        var y = ReadUInt24(data.Slice(3, 3)) * 2;
        var width = ReadUInt24(data.Slice(6, 3)) + 1;
        var height = ReadUInt24(data.Slice(9, 3)) + 1;
        if ((long)x + width > canvasWidth || (long)y + height > canvasHeight)
            throw InvalidImage("Invalid WebP frame dimensions.");

        var position = 16;
        var hasAlpha = data.Slice(position, 4).SequenceEqual("ALPH"u8);
        if (hasAlpha)
        {
            var alphaLength = BinaryPrimitives.ReadUInt32LittleEndian(data.Slice(position + 4, 4));
            var afterAlpha = (long)position + 8 + alphaLength + (alphaLength & 1);
            if (afterAlpha > data.Length - 8)
                throw InvalidImage("Truncated WebP alpha chunk.");
            position = (int)afterAlpha;
        }

        var type = data.Slice(position, 4);
        if (!type.SequenceEqual("VP8 "u8) && !(type.SequenceEqual("VP8L"u8) && !hasAlpha))
            throw InvalidImage("Invalid WebP frame pixel chunk.");
        var pixelLength = BinaryPrimitives.ReadUInt32LittleEndian(data.Slice(position + 4, 4));
        // ReadFrame does not seek to the declared ANMF end. No nested trailing chunks
        // may remain for the outer decoder to reinterpret as another frame.
        if ((long)position + 8 + pixelLength + (pixelLength & 1) != data.Length)
            throw InvalidImage("The WebP frame does not match its chunk envelope.");
    }

    // Only validate chunk envelopes and animation counts. ImageSharp owns PNG payload/CRC decoding.
    // A non-animated IDAT default image is retained as an extra stored frame by ImageSharp 3.1.12.
    internal static int CountPngFrames(MemoryStream input, CancellationToken cancellationToken)
    {
        var bytes = input.GetBuffer().AsSpan(0, (int)input.Length);
        ReadOnlySpan<byte> signature = [137, 80, 78, 71, 13, 10, 26, 10];
        if (bytes.Length < 8 || !bytes[..8].SequenceEqual(signature))
            throw InvalidImage("Invalid PNG image.");

        long position = 8;
        var chunks = 0;
        var width = 0;
        var height = 0;
        uint? declaredFrames = null;
        var frameControls = 0;
        var hasDefaultData = false;
        var rootIncluded = false;
        var currentFrameIsRoot = false;
        var frameNeedsData = false;
        var frameControlAfterDefault = false;
        var previousChunkWasFrameData = false;

        while (position < bytes.Length)
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (++chunks > MaximumContainerChunks || bytes.Length - position < 12)
                throw InvalidImage("Invalid PNG chunk envelope.");
            var offset = (int)position;
            var length = BinaryPrimitives.ReadUInt32BigEndian(bytes.Slice(offset, 4));
            var next = position + 12 + length;
            if (next > bytes.Length)
                throw InvalidImage("Truncated PNG chunk.");
            var type = bytes.Slice(offset + 4, 4);
            var data = bytes.Slice(offset + 8, (int)length);

            // ImageSharp 3.1.12 resynchronizes on invalid type bytes instead of
            // skipping their declared envelope. Keep both parsers on the same
            // chunk boundaries so hidden frame controls cannot escape counting.
            foreach (var value in type)
            {
                if ((value < 'A' || value > 'Z') && (value < 'a' || value > 'z'))
                    throw InvalidImage("Invalid PNG chunk type.");
            }

            if (type.SequenceEqual("IHDR"u8))
            {
                if (chunks != 1 || length != 13)
                    throw InvalidImage("Invalid PNG header.");
                var headerWidth = BinaryPrimitives.ReadUInt32BigEndian(data[..4]);
                var headerHeight = BinaryPrimitives.ReadUInt32BigEndian(data.Slice(4, 4));
                if (headerWidth > MaximumDimension || headerHeight > MaximumDimension)
                    throw InvalidImage("Image dimensions exceed the supported processing limits.");
                width = (int)headerWidth;
                height = (int)headerHeight;
                ValidateSize(width, height);
            }
            else if (chunks == 1)
            {
                throw InvalidImage("The PNG header must be first.");
            }
            else if (type.SequenceEqual("acTL"u8))
            {
                if (declaredFrames.HasValue || hasDefaultData || length != 8)
                    throw InvalidImage("Invalid PNG animation control.");
                declaredFrames = BinaryPrimitives.ReadUInt32BigEndian(data[..4]);
                if (declaredFrames is 0 or > MaximumFrames)
                    throw InvalidImage("The image has too many frames.");
            }
            else if (type.SequenceEqual("fcTL"u8))
            {
                if (!declaredFrames.HasValue || frameNeedsData || length != 26 || ++frameControls > MaximumFrames)
                    throw InvalidImage("Invalid PNG frame control.");
                currentFrameIsRoot = !hasDefaultData;
                rootIncluded |= currentFrameIsRoot;
                frameControlAfterDefault |= hasDefaultData;
                frameNeedsData = true;
                var frameWidth = BinaryPrimitives.ReadUInt32BigEndian(data.Slice(4, 4));
                var frameHeight = BinaryPrimitives.ReadUInt32BigEndian(data.Slice(8, 4));
                var x = BinaryPrimitives.ReadUInt32BigEndian(data.Slice(12, 4));
                var y = BinaryPrimitives.ReadUInt32BigEndian(data.Slice(16, 4));
                if (frameWidth == 0 || frameHeight == 0 || (long)x + frameWidth > width || (long)y + frameHeight > height)
                    throw InvalidImage("Invalid PNG frame dimensions.");
            }
            else if (type.SequenceEqual("IDAT"u8))
            {
                if (frameControlAfterDefault)
                    throw InvalidImage("Invalid PNG default-frame data order.");
                hasDefaultData = true;
                if (currentFrameIsRoot)
                    frameNeedsData = false;
            }
            else if (type.SequenceEqual("fdAT"u8))
            {
                // A split data group makes the 3.1.12 decoder add another stored frame
                // without another fcTL. Reject that representation before allocating pixels.
                if (!declaredFrames.HasValue || !hasDefaultData || currentFrameIsRoot || frameControls == 0 || length < 4 ||
                    (!frameNeedsData && !previousChunkWasFrameData))
                    throw InvalidImage("Invalid PNG animation-frame data.");
                frameNeedsData = false;
            }
            else if (type.SequenceEqual("IEND"u8))
            {
                if (length != 0 || !hasDefaultData || frameNeedsData || next != bytes.Length ||
                    (declaredFrames.HasValue && declaredFrames.Value != frameControls))
                    throw InvalidImage("Incomplete PNG animation or chunk envelope.");
                var frames = declaredFrames.HasValue ? frameControls + (rootIncluded ? 0 : 1) : 1;
                if (frames > MaximumFrames || (long)width * height * frames > MaximumCanvasPixels)
                    throw InvalidImage("The image has too many frames or decoded pixels.");
                return frames;
            }

            previousChunkWasFrameData = type.SequenceEqual("fdAT"u8);
            position = next;
        }

        throw InvalidImage("The PNG end chunk is missing.");
    }

    internal static void RemovePngIccChunks(MemoryStream input, CancellationToken cancellationToken)
    {
        // 3.1.12 ignores SkipMetadata for PNG iCCP and inflates each profile into
        // managed arrays outside the pixel allocator. Profiles were already
        // discarded before transforms; remove these opaque envelopes before
        // identification/decoding instead. Do not inspect ICC tag contents.
        var bytes = input.GetBuffer().AsSpan(0, (int)input.Length);
        var write = 8;
        var position = 8;
        var chunks = 0;
        while (position < bytes.Length)
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (++chunks > MaximumContainerChunks || bytes.Length - position < 12)
                throw InvalidImage("Invalid PNG chunk envelope.");
            var length = BinaryPrimitives.ReadUInt32BigEndian(bytes.Slice(position, 4));
            var total = 12L + length;
            if (total > bytes.Length - position)
                throw InvalidImage("Truncated PNG chunk.");
            if (!bytes.Slice(position + 4, 4).SequenceEqual("iCCP"u8))
            {
                bytes.Slice(position, (int)total).CopyTo(bytes[write..]);
                write += (int)total;
            }
            position += (int)total;
        }
        input.SetLength(write);
        input.Position = 0;
    }

    internal static ValidationException InvalidImage(string message) => new("File", message);

    internal sealed class ProcessingSession : IDisposable
    {
        private int disposed;

        internal ProcessingSession()
        {
            Configuration = new Configuration(new JpegConfigurationModule(), new PngConfigurationModule(),
                new GifConfigurationModule(), new WebpConfigurationModule())
            {
                MaxDegreeOfParallelism = 1,
                MemoryAllocator = new AccountingMemoryAllocator(SharedAllocator)
            };
        }

        internal Configuration Configuration { get; }

        internal DecoderOptions DecoderOptions(uint maxFrames) => new()
        {
            Configuration = Configuration,
            SkipMetadata = true,
            MaxFrames = maxFrames
        };

        public void Dispose()
        {
            if (Interlocked.Exchange(ref disposed, 1) == 0)
                ProcessingGate.Release();
        }
    }

    /// <summary>Caps live requested ImageSharp buffer bytes, not managed metadata arrays or total process RAM.</summary>
    private sealed class AccountingMemoryAllocator(MemoryAllocator inner) : MemoryAllocator
    {
        private long allocatedBytes;

        // Route MemoryGroup allocations through this allocator's public Allocate override.
        protected override int GetBufferCapacityInBytes() => 4 * 1024 * 1024;

        public override IMemoryOwner<T> Allocate<T>(int length, AllocationOptions options = AllocationOptions.None)
        {
            if (length < 0)
                throw new InvalidMemoryOperationException("Negative image buffer size.");
            var bytes = (long)Unsafe.SizeOf<T>() * length;
            while (true)
            {
                var current = Volatile.Read(ref allocatedBytes);
                if (bytes > MaximumActiveBufferBytes - current)
                    throw new InvalidMemoryOperationException("The image processing buffer budget was exceeded.");
                if (Interlocked.CompareExchange(ref allocatedBytes, current + bytes, current) == current)
                    break;
            }

            IMemoryOwner<T>? owner = null;
            try
            {
                owner = inner.Allocate<T>(length, options);
                return new AccountedOwner<T>(owner, this, bytes);
            }
            catch
            {
                owner?.Dispose();
                Interlocked.Add(ref allocatedBytes, -bytes);
                throw;
            }
        }

        private sealed class AccountedOwner<T>(IMemoryOwner<T> owner, AccountingMemoryAllocator allocator, long bytes) : IMemoryOwner<T>
        {
            private IMemoryOwner<T>? currentOwner = owner;

            public Memory<T> Memory => Volatile.Read(ref currentOwner)?.Memory ?? throw new ObjectDisposedException(nameof(AccountedOwner<T>));

            public void Dispose()
            {
                var current = Interlocked.Exchange(ref currentOwner, null);
                if (current is null)
                    return;
                try
                {
                    current.Dispose();
                }
                finally
                {
                    Interlocked.Add(ref allocator.allocatedBytes, -bytes);
                }
            }
        }
    }
}
