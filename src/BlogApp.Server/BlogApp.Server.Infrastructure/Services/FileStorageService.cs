using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Infrastructure.Services.Helpers;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using SixLabors.ImageSharp;
using SixLabors.ImageSharp.Formats.Webp;
using SixLabors.ImageSharp.Processing;

namespace BlogApp.Server.Infrastructure.Services;

/// <summary>
/// Local file storage servisi implementasyonu
/// </summary>
public class FileStorageService(IHostEnvironment environment, ILogger<FileStorageService> logger) : IFileStorageService
{
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
        options ??= new ImageUploadOptions();

        try
        {
            // Magic bytes validation before processing
            var contentType = GetContentTypeFromExtension(fileName);
            var validationResult = await FileValidationHelper.ValidateImageAsync(fileStream, fileName, contentType);

            if (!validationResult.IsValid)
            {
                throw new InvalidOperationException($"File validation failed: {validationResult.ErrorMessage}");
            }

            // Reset stream position after validation
            fileStream.Position = 0;

            using var image = await Image.LoadAsync(fileStream, cancellationToken);

            // Strip EXIF and other metadata for security
            image.Metadata.ExifProfile = null;
            image.Metadata.XmpProfile = null;
            image.Metadata.IccProfile = null;
            image.Metadata.IptcProfile = null;

            // Orijinal boyutları kaydet
            var originalWidth = image.Width;
            var originalHeight = image.Height;

            // Boyutlandır (max boyutları aşıyorsa)
            if (image.Width > options.MaxWidth || image.Height > options.MaxHeight)
            {
                image.Mutate(x => x.Resize(new ResizeOptions
                {
                    Mode = ResizeMode.Max,
                    Size = new Size(options.MaxWidth, options.MaxHeight)
                }));
            }

            // Dosya adını oluştur
            var baseFileName = Path.GetFileNameWithoutExtension(fileName);
            var uniqueId = Guid.NewGuid().ToString("N")[..8];
            var extension = options.ConvertToWebP ? ".webp" : Path.GetExtension(fileName);
            var uniqueFileName = $"{baseFileName}_{uniqueId}{extension}";

            // Images klasörünü oluştur
            var imagesFolder = Path.Combine(_uploadsFolder, "images");
            if (!Directory.Exists(imagesFolder))
                Directory.CreateDirectory(imagesFolder);

            var filePath = Path.Combine(imagesFolder, uniqueFileName);

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
                var thumbnailResult = await CreateThumbnailAsync(image, baseFileName, uniqueId, options, imagesFolder, cancellationToken);
                result.ThumbnailUrl = thumbnailResult;
            }

            logger.LogInformation("Image uploaded: {Url}, Size: {Width}x{Height}, FileSize: {FileSize}KB",
                result.Url, result.Width, result.Height, result.FileSize / 1024);

            return result;
        }
        catch (Exception ex)
        {
            logger.LogError(ex, "Error uploading image {FileName}", fileName);
            throw;
        }
    }

    private static async Task<string> CreateThumbnailAsync(Image image, string baseFileName, string uniqueId, ImageUploadOptions options, string folder, CancellationToken cancellationToken)
    {
        using var thumbnail = image.Clone(x => x.Resize(new ResizeOptions
        {
            Mode = ResizeMode.Crop,
            Size = new Size(options.ThumbnailWidth, options.ThumbnailHeight)
        }));

        var extension = options.ConvertToWebP ? ".webp" : ".jpg";
        var thumbnailFileName = $"{baseFileName}_{uniqueId}_thumb{extension}";
        var thumbnailPath = Path.Combine(folder, thumbnailFileName);

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

            if (File.Exists(filePath))
            {
                File.Delete(filePath);
                logger.LogInformation("File deleted: {FilePath}", filePath);
                return Task.FromResult(true);
            }

            return Task.FromResult(false);
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
