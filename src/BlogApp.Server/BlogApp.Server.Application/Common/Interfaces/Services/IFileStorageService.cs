namespace BlogApp.Server.Application.Common.Interfaces.Services;

/// <summary>
/// Dosya depolama servisi arayüzü
/// </summary>
public interface IFileStorageService
{
    /// <summary>
    /// Dosya yükler ve URL döner
    /// </summary>
    Task<string> UploadAsync(Stream fileStream, string fileName, string contentType, CancellationToken cancellationToken = default);

    /// <summary>
    /// Görsel yükler, optimize eder ve URL döner
    /// </summary>
    Task<ImageUploadResult> UploadImageAsync(Stream fileStream, string fileName, ImageUploadOptions? options = null, CancellationToken cancellationToken = default);

    /// <summary>
    /// Dosyayı siler
    /// </summary>
    Task<bool> DeleteAsync(string fileUrl, CancellationToken cancellationToken = default);

    /// <summary>
    /// Dosyanın var olup olmadığını kontrol eder
    /// </summary>
    Task<bool> ExistsAsync(string fileUrl, CancellationToken cancellationToken = default);
}

/// <summary>
/// Görsel yükleme seçenekleri
/// </summary>
public class ImageUploadOptions
{
    public int MaxWidth { get; set; } = 1920;
    public int MaxHeight { get; set; } = 1080;
    public int Quality { get; set; } = 85;
    public bool ConvertToWebP { get; set; } = true;
    public bool GenerateThumbnail { get; set; } = true;
    public int ThumbnailWidth { get; set; } = 400;
    public int ThumbnailHeight { get; set; } = 300;
}

/// <summary>
/// Görsel yükleme sonucu
/// </summary>
public class ImageUploadResult
{
    public string Url { get; set; } = default!;
    public string? ThumbnailUrl { get; set; }
    public int Width { get; set; }
    public int Height { get; set; }
    public long FileSize { get; set; }
    public string ContentType { get; set; } = default!;
}


