using BlogApp.Core.Application.Common.Interfaces.Services;
using BlogApp.Infrastructure.Services.Helpers;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using SixLabors.ImageSharp;
using SixLabors.ImageSharp.Formats.Webp;
using SixLabors.ImageSharp.Memory;
using SixLabors.ImageSharp.Processing;

namespace BlogApp.Infrastructure.Services;

/// <summary>
/// Local file storage servisi implementasyonu
/// </summary>
public class FileStorageService(IHostEnvironment environment, ILogger<FileStorageService> logger) : IFileStorageService
{
    private static readonly HashSet<string> AllowedExtensions = new(StringComparer.OrdinalIgnoreCase)
    {
        ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"
    };

    private readonly string _uploadsFolder = InitializeUploadsFolder(environment.ContentRootPath);

    private static string InitializeUploadsFolder(string contentRootPath)
    {
        var uploadsFolder = Path.Combine(contentRootPath, "uploads");
        if (!Directory.Exists(uploadsFolder))
            Directory.CreateDirectory(uploadsFolder);
        return uploadsFolder;
    }

    public async Task<string> UploadAsync(Stream fileStream, string fileName, string contentType, CancellationToken cancellationToken = default)
    {
        try
        {
            var uniqueFileName = GenerateUniqueFileName(fileName);
            var filePath = Path.Combine(_uploadsFolder, uniqueFileName);

            await using var outputStream = new FileStream(filePath, FileMode.Create);
            await fileStream.CopyToAsync(outputStream, cancellationToken);

            return $"/uploads/{uniqueFileName}";
        }
        catch (Exception ex)
        {
            logger.LogError(ex, "Error uploading file {FileName}", fileName);
            throw;
        }
    }

    public async Task<ImageUploadResult> UploadImageAsync(Stream fileStream, string fileName, ImageUploadOptions? options = null, CancellationToken cancellationToken = default)
    {
        options = ImageProcessingSecurity.ValidateOptions(options ?? new ImageUploadOptions());
        using var processing = await ImageProcessingSecurity.EnterAsync(cancellationToken).ConfigureAwait(false);
        var outputFiles = new List<string>();
        var completed = false;
        try
        {
            // Snapshot and bound the actual bytes inside the process-wide processing gate.
            using var input = await ImageProcessingSecurity.CopyInputAsync(fileStream, cancellationToken).ConfigureAwait(false);
            var contentType = GetContentTypeFromExtension(fileName);
            var validationResult = await FileValidationHelper.ValidateImageAsync(input, fileName, contentType);

            if (!validationResult.IsValid)
                throw ImageProcessingSecurity.InvalidImage(validationResult.ErrorMessage ?? "Invalid image.");

            var expectedFrames = contentType switch
            {
                "image/png" => ImageProcessingSecurity.CountPngFrames(input, cancellationToken),
                "image/webp" => ImageProcessingSecurity.CountWebpFrames(input, cancellationToken),
                _ => (int?)null
            };
            if (contentType == "image/png")
                ImageProcessingSecurity.RemovePngIccChunks(input, cancellationToken);

            Image image;
            try
            {
                input.Position = 0;
                var identifyOptions = processing.DecoderOptions(contentType is "image/png" or "image/webp"
                    ? uint.MaxValue : ImageProcessingSecurity.MaximumFrames + 1u);
                // The 3.1.12 full PNG Identify path mis-skips fdAT data on valid APNGs.
                // Our envelope pass validated the entire container; let ImageSharp identify
                // the original IHDR without traversing animation data a second time.
                using var pngHeader = contentType == "image/png"
                    ? new MemoryStream(input.GetBuffer(), 0, 33, writable: false, publiclyVisible: true)
                    : null;
                var info = await Image.IdentifyAsync(identifyOptions, pngHeader ?? input, cancellationToken).ConfigureAwait(false);
                var allowedFrames = ImageProcessingSecurity.GetAllowedFrameCount(info);
                expectedFrames ??= Math.Max(1, info.FrameMetadataCollection.Count);
                if (expectedFrames > allowedFrames)
                    throw ImageProcessingSecurity.InvalidImage("The image has too many frames or decoded pixels.");
                ImageProcessingSecurity.ValidatePlannedPixels(info.Width, info.Height, expectedFrames.Value, options);

                input.Position = 0;
                // PNG and WebP containers have already been counted in full. Their 3.1.12
                // MaxFrames counters do not reliably represent the number of stored frames.
                var decodeOptions = processing.DecoderOptions(contentType is "image/png" or "image/webp"
                    ? uint.MaxValue : (uint)allowedFrames + 1);
                image = await Image.LoadAsync(decodeOptions, input, cancellationToken).ConfigureAwait(false);
                if (image is null)
                    throw ImageProcessingSecurity.InvalidImage("The image contains no decodable frames.");
                try
                {
                    ImageProcessingSecurity.ValidateDecodedImage(image, allowedFrames, options);
                    if (image.Width != info.Width || image.Height != info.Height || image.Frames.Count != expectedFrames)
                        throw ImageProcessingSecurity.InvalidImage("The decoded image does not match its validated container.");
                }
                catch
                {
                    image.Dispose();
                    throw;
                }
            }
            catch (Exception ex) when (ex is UnknownImageFormatException or ImageFormatException or
                                       InvalidMemoryOperationException or NotSupportedException or ArgumentException or
                                       OverflowException or EndOfStreamException or InvalidDataException)
            {
                throw ImageProcessingSecurity.InvalidImage("The image is malformed or exceeds the supported processing limits.");
            }

            using var decodedImage = image;

            // SkipMetadata is partial in 3.1.12 (PNG still inflates iCCP). Never read ICC Entries.
            image.Metadata.ExifProfile = null;
            image.Metadata.XmpProfile = null;
            image.Metadata.IccProfile = null;
            image.Metadata.IptcProfile = null;
            foreach (var frame in image.Frames)
            {
                frame.Metadata.ExifProfile = null;
                frame.Metadata.XmpProfile = null;
                frame.Metadata.IccProfile = null;
                frame.Metadata.IptcProfile = null;
            }

            cancellationToken.ThrowIfCancellationRequested();
            if (image.Width > options.MaxWidth || image.Height > options.MaxHeight)
            {
                image.Mutate(x => x.Resize(new ResizeOptions
                {
                    Mode = ResizeMode.Max,
                    Size = new Size(options.MaxWidth, options.MaxHeight)
                }));
            }

            ImageProcessingSecurity.ValidateDecodedImage(image, ImageProcessingSecurity.MaximumFrames, options);
            cancellationToken.ThrowIfCancellationRequested();

            var safeFileName = FileValidationHelper.SanitizeFileName(fileName);
            var baseFileName = Path.GetFileNameWithoutExtension(safeFileName);
            var uniqueId = Guid.NewGuid().ToString("N")[..8];
            var extension = options.ConvertToWebP ? ".webp" : Path.GetExtension(safeFileName);
            var uniqueFileName = $"{baseFileName}_{uniqueId}{extension}";

            // Images klasörünü oluştur (thread-safe: Directory.CreateDirectory doesn't throw if exists)
            var imagesFolder = Path.Combine(_uploadsFolder, "images");
            Directory.CreateDirectory(imagesFolder); // Idempotent - safe for concurrent calls

            var filePath = Path.Combine(imagesFolder, uniqueFileName);
            outputFiles.Add(filePath);

            // Kaydet
            if (options.ConvertToWebP)
            {
                var encoder = new WebpEncoder { Quality = options.Quality };
                await image.SaveAsync(filePath, encoder, cancellationToken);
            }
            else
            {
                await image.SaveAsync(filePath, cancellationToken);
            }

            var fileInfo = new FileInfo(filePath);

            var result = new ImageUploadResult
            {
                Url = $"/uploads/images/{uniqueFileName}",
                Width = image.Width,
                Height = image.Height,
                FileSize = fileInfo.Length,
                ContentType = options.ConvertToWebP ? "image/webp" : GetContentType(extension)
            };

            // Thumbnail oluştur
            if (options.GenerateThumbnail)
            {
                var thumbnailResult = await CreateThumbnailAsync(image, baseFileName, uniqueId, options, imagesFolder, outputFiles, cancellationToken);
                result.ThumbnailUrl = thumbnailResult;
            }

            logger.LogInformation("Image uploaded: {Url}, Size: {Width}x{Height}, FileSize: {FileSize}KB",
                result.Url, result.Width, result.Height, result.FileSize / 1024);

            cancellationToken.ThrowIfCancellationRequested();
            completed = true;
            return result;
        }
        catch (InvalidMemoryOperationException)
        {
            throw ImageProcessingSecurity.InvalidImage("The image processing buffer budget was exceeded.");
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            throw;
        }
        catch (Exception ex)
        {
            logger.LogError(ex, "Error uploading image {FileName}", fileName);
            throw;
        }
        finally
        {
            if (!completed)
            {
                foreach (var path in outputFiles)
                {
                    try
                    {
                        File.Delete(path);
                    }
                    catch (Exception cleanupError) when (cleanupError is IOException or UnauthorizedAccessException)
                    {
                        logger.LogWarning(cleanupError, "Could not remove incomplete image output {FilePath}", path);
                    }
                }
            }
        }
    }

    private static async Task<string> CreateThumbnailAsync(Image image, string baseFileName, string uniqueId, ImageUploadOptions options, string folder, List<string> outputFiles, CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        using var thumbnail = image.Clone(x => x.Resize(new ResizeOptions
        {
            Mode = ResizeMode.Crop,
            Size = new Size(options.ThumbnailWidth, options.ThumbnailHeight)
        }));
        ImageProcessingSecurity.ValidateDecodedImage(thumbnail, ImageProcessingSecurity.MaximumFrames, options, includePlannedThumbnail: false);
        cancellationToken.ThrowIfCancellationRequested();

        var extension = options.ConvertToWebP ? ".webp" : ".jpg";
        var thumbnailFileName = $"{baseFileName}_{uniqueId}_thumb{extension}";
        var thumbnailPath = Path.Combine(folder, thumbnailFileName);
        outputFiles.Add(thumbnailPath);

        if (options.ConvertToWebP)
        {
            var encoder = new WebpEncoder { Quality = options.Quality };
            await thumbnail.SaveAsync(thumbnailPath, encoder, cancellationToken);
        }
        else
        {
            await thumbnail.SaveAsync(thumbnailPath, cancellationToken);
        }

        return $"/uploads/images/{thumbnailFileName}";
    }

    public Task<bool> DeleteAsync(string fileUrl, CancellationToken cancellationToken = default)
    {
        try
        {
            if (string.IsNullOrEmpty(fileUrl))
                return Task.FromResult(false);

            // URL'den dosya yolunu çıkar
            var relativePath = fileUrl.TrimStart('/').Replace('/', Path.DirectorySeparatorChar);
            var filePath = Path.Combine(environment.ContentRootPath, relativePath);

            // Path Traversal koruması: Dosyanın uploads klasörü içinde olduğunu doğrula
            var fullPath = Path.GetFullPath(filePath);
            var uploadsFullPath = Path.GetFullPath(_uploadsFolder);

            if (!fullPath.StartsWith(uploadsFullPath, StringComparison.OrdinalIgnoreCase))
            {
                // GÜVENLİK DÜZELTMESİ: Path Traversal (Dizin Geçişi) saldırılarına karşı koruma.
                // Kullanıcının "uploads" klasörü dışındaki dosyalara erişmesini engeller.
                logger.LogWarning("Path traversal attempt detected: {FileUrl}", fileUrl);
                return Task.FromResult(false);
            }

            // TOCTOU FIX: File.Exists + File.Delete yerine direkt delete + exception handling
            // Bu yaklaşım race condition'ı önler
            try
            {
                File.Delete(filePath);
                logger.LogInformation("File deleted: {FilePath}", filePath);
                return Task.FromResult(true);
            }
            catch (FileNotFoundException)
            {
                // Dosya zaten silinmiş - hata değil
                return Task.FromResult(false);
            }
            catch (DirectoryNotFoundException)
            {
                // Parent directory mevcut değil - hata değil
                return Task.FromResult(false);
            }
        }
        catch (Exception ex)
        {
            logger.LogError(ex, "Error deleting file {FileUrl}", fileUrl);
            return Task.FromResult(false);
        }
    }

    public Task<bool> ExistsAsync(string fileUrl, CancellationToken cancellationToken = default)
    {
        if (string.IsNullOrEmpty(fileUrl))
            return Task.FromResult(false);

        var relativePath = fileUrl.TrimStart('/').Replace('/', Path.DirectorySeparatorChar);
        var filePath = Path.Combine(environment.ContentRootPath, relativePath);

        // Path Traversal koruması
        var fullPath = Path.GetFullPath(filePath);
        var uploadsFullPath = Path.GetFullPath(_uploadsFolder);

        if (!fullPath.StartsWith(uploadsFullPath, StringComparison.OrdinalIgnoreCase))
            return Task.FromResult(false);

        return Task.FromResult(File.Exists(filePath));
    }

    private static string GenerateUniqueFileName(string fileName)
    {
        // GÜVENLİK DÜZELTMESİ: Dosya adını temizleyerek potansiyel zararlı karakterleri kaldır.
        var extension = Path.GetExtension(fileName);

        // Uzantı beyaz listede değilse güvenli varsayılana düş
        if (!AllowedExtensions.Contains(extension))
            extension = ".bin";

        var baseName = Path.GetFileNameWithoutExtension(fileName);

        // Basit sanitizasyon: sadece güvenli karakterlere izin ver
        baseName = new string(baseName.Where(c => char.IsLetterOrDigit(c) || c == '-' || c == '_').ToArray());

        var uniqueId = Guid.NewGuid().ToString("N")[..8];
        return $"{baseName}_{uniqueId}{extension}";
    }

    private static string GetContentType(string extension) => extension.ToLowerInvariant() switch
    {
        ".jpg" or ".jpeg" => "image/jpeg",
        ".png" => "image/png",
        ".gif" => "image/gif",
        ".webp" => "image/webp",
        ".svg" => "image/svg+xml",
        _ => "application/octet-stream"
    };

    private static string GetContentTypeFromExtension(string fileName)
    {
        var extension = Path.GetExtension(fileName);
        return GetContentType(extension);
    }
}
