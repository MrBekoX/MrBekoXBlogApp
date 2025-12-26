using BlogApp.Server.Application.Common.Interfaces;
using BlogApp.Server.Application.Common.Models;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;

namespace BlogApp.Server.Api.Controllers;

/// <summary>
/// Media upload API controller
/// </summary>
[Authorize(Roles = "Admin,Editor,Author")]
public class MediaController : ApiControllerBase
{
    private readonly IFileStorageService _fileStorageService;
    private readonly ILogger<MediaController> _logger;
    
    private static readonly string[] AllowedImageTypes = { "image/jpeg", "image/png", "image/gif", "image/webp" };
    private const long MaxFileSize = 10 * 1024 * 1024; // 10MB

    public MediaController(IFileStorageService fileStorageService, ILogger<MediaController> logger)
    {
        _fileStorageService = fileStorageService;
        _logger = logger;
    }

    /// <summary>
    /// Upload an image
    /// </summary>
    [HttpPost("upload/image")]
    [ProducesResponseType(typeof(ApiResponse<ImageUploadResult>), StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status400BadRequest)]
    [RequestSizeLimit(MaxFileSize)]
    public async Task<IActionResult> UploadImage(IFormFile file, [FromQuery] bool generateThumbnail = true)
    {
        if (file == null || file.Length == 0)
            return BadRequest(ApiResponse<ImageUploadResult>.FailureResult("No file uploaded"));

        // GÜVENLİK DÜZELTMESİ: Dosya türü kontrolü (File Type Validation)
        // Sadece izin verilen güvenli dosya türlerini (resimler) kabul et.
        // Zararlı çalıştırılabilir dosyaların (.exe, .sh, .php vb.) yüklenmesini engeller.
        if (!AllowedImageTypes.Contains(file.ContentType.ToLowerInvariant()))
            return BadRequest(ApiResponse<ImageUploadResult>.FailureResult("Invalid file type. Allowed: JPEG, PNG, GIF, WebP"));

        // GÜVENLİK DÜZELTMESİ: Dosya boyutu sınırı (File Size Limit)
        // DoS (Denial of Service) saldırılarını ve sunucu disk alanının doldurulmasını önlemek için boyut sınırı.
        if (file.Length > MaxFileSize)
            return BadRequest(ApiResponse<ImageUploadResult>.FailureResult($"File too large. Maximum size: {MaxFileSize / 1024 / 1024}MB"));

        try
        {
            await using var stream = file.OpenReadStream();
            
            var options = new ImageUploadOptions
            {
                GenerateThumbnail = generateThumbnail,
                ConvertToWebP = true,
                Quality = 85
            };
            
            var result = await _fileStorageService.UploadImageAsync(stream, file.FileName, options);
            
            return Ok(ApiResponse<ImageUploadResult>.SuccessResult(result, "Image uploaded successfully"));
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error uploading image");
            return BadRequest(ApiResponse<ImageUploadResult>.FailureResult("Error uploading image"));
        }
    }

    /// <summary>
    /// Upload multiple images
    /// </summary>
    [HttpPost("upload/images")]
    [ProducesResponseType(typeof(ApiResponse<List<ImageUploadResult>>), StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status400BadRequest)]
    [RequestSizeLimit(50 * 1024 * 1024)] // 50MB for multiple files
    public async Task<IActionResult> UploadImages(List<IFormFile> files)
    {
        if (files == null || files.Count == 0)
            return BadRequest(ApiResponse<List<ImageUploadResult>>.FailureResult("No files uploaded"));

        if (files.Count > 10)
            return BadRequest(ApiResponse<List<ImageUploadResult>>.FailureResult("Maximum 10 files at once"));

        var results = new List<ImageUploadResult>();
        var errors = new List<string>();

        foreach (var file in files)
        {
            if (!AllowedImageTypes.Contains(file.ContentType.ToLowerInvariant()))
            {
                errors.Add($"{file.FileName}: Invalid file type");
                continue;
            }

            if (file.Length > MaxFileSize)
            {
                errors.Add($"{file.FileName}: File too large");
                continue;
            }

            try
            {
                await using var stream = file.OpenReadStream();
                var result = await _fileStorageService.UploadImageAsync(stream, file.FileName);
                results.Add(result);
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Error uploading image {FileName}", file.FileName);
                errors.Add($"{file.FileName}: Upload failed");
            }
        }

        var message = errors.Count > 0 
            ? $"Uploaded {results.Count} files. Errors: {string.Join(", ", errors)}" 
            : $"Uploaded {results.Count} files successfully";

        return Ok(ApiResponse<List<ImageUploadResult>>.SuccessResult(results, message));
    }

    /// <summary>
    /// Delete an uploaded file
    /// </summary>
    [HttpDelete]
    [ProducesResponseType(StatusCodes.Status204NoContent)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    public async Task<IActionResult> DeleteFile([FromQuery] string url)
    {
        if (string.IsNullOrEmpty(url))
            return BadRequest(ApiResponse<object>.FailureResult("URL is required"));

        var deleted = await _fileStorageService.DeleteAsync(url);
        
        if (!deleted)
            return NotFound(ApiResponse<object>.FailureResult("File not found"));

        return NoContent();
    }
}

