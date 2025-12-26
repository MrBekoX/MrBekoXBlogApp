using BlogApp.Server.Application.Common.Interfaces;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using SixLabors.ImageSharp;
using SixLabors.ImageSharp.Formats.Webp;
using SixLabors.ImageSharp.Processing;

namespace BlogApp.Server.Infrastructure.Services;

/// <summary>
/// Local file storage servisi implementasyonu
/// </summary>
public class FileStorageService : IFileStorageService
{
    private readonly IHostEnvironment _environment;
    private readonly ILogger<FileStorageService> _logger;
    private readonly string _uploadsFolder;

    public FileStorageService(IHostEnvironment environment, ILogger<FileStorageService> logger)
    {
        _environment = environment;
        _logger = logger;
        _uploadsFolder = Path.Combine(_environment.ContentRootPath, "uploads");
        
        // Uploads klasörünü oluştur
        if (!Directory.Exists(_uploadsFolder))
            Directory.CreateDirectory(_uploadsFolder);
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
            _logger.LogError(ex, "Error uploading file {FileName}", fileName);
            throw;
        }
    }

    public async Task<ImageUploadResult> UploadImageAsync(Stream fileStream, string fileName, ImageUploadOptions? options = null, CancellationToken cancellationToken = default)
    {
        options ??= new ImageUploadOptions();
        
        try
        {
            using var image = await Image.LoadAsync(fileStream, cancellationToken);
            
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

            _logger.LogInformation("Image uploaded: {Url}, Size: {Width}x{Height}, FileSize: {FileSize}KB", 
                result.Url, result.Width, result.Height, result.FileSize / 1024);

            return result;
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error uploading image {FileName}", fileName);
            throw;
        }
    }

    private async Task<string> CreateThumbnailAsync(Image image, string baseFileName, string uniqueId, ImageUploadOptions options, string folder, CancellationToken cancellationToken)
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
            var filePath = Path.Combine(_environment.ContentRootPath, relativePath);

            // Path Traversal koruması: Dosyanın uploads klasörü içinde olduğunu doğrula
            var fullPath = Path.GetFullPath(filePath);
            var uploadsFullPath = Path.GetFullPath(_uploadsFolder);

            if (!fullPath.StartsWith(uploadsFullPath, StringComparison.OrdinalIgnoreCase))
            {
                // GÜVENLİK DÜZELTMESİ: Path Traversal (Dizin Geçişi) saldırılarına karşı koruma.
                // Kullanıcının "uploads" klasörü dışındaki dosyalara erişmesini engeller.
                _logger.LogWarning("Path traversal attempt detected: {FileUrl}", fileUrl);
                return Task.FromResult(false);
            }

            if (File.Exists(filePath))
            {
                File.Delete(filePath);
                _logger.LogInformation("File deleted: {FilePath}", filePath);
                return Task.FromResult(true);
            }

            return Task.FromResult(false);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error deleting file {FileUrl}", fileUrl);
            return Task.FromResult(false);
        }
    }

    public Task<bool> ExistsAsync(string fileUrl, CancellationToken cancellationToken = default)
    {
        if (string.IsNullOrEmpty(fileUrl))
            return Task.FromResult(false);

        var relativePath = fileUrl.TrimStart('/').Replace('/', Path.DirectorySeparatorChar);
        var filePath = Path.Combine(_environment.ContentRootPath, relativePath);

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
}

