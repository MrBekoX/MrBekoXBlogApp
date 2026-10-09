namespace BlogApp.Core.Application.Common.Utilities;

/// <summary>
/// Image file validation utilities — magic byte checking and filename sanitization.
/// </summary>
public static class ImageValidation
{
    public static readonly string[] AllowedImageTypes = ["image/jpeg", "image/png", "image/gif", "image/webp"];
    public const long MaxFileSize = 10 * 1024 * 1024; // 10MB

    /// <summary>
    /// Validates file content by checking magic bytes.
    /// Prevents attackers from uploading malicious files with fake extensions.
    /// </summary>
    public static bool IsValidImageFile(Stream stream, string contentType)
    {
        stream.Position = 0;
        var header = new byte[12];
        var bytesRead = stream.Read(header, 0, 12);
        stream.Position = 0;

        if (bytesRead < 4)
            return false;

        var lowerContentType = contentType.ToLowerInvariant();

        if (lowerContentType.Contains("jpeg") || lowerContentType.Contains("jpg"))
        {
            return header[0] == 0xFF && header[1] == 0xD8 && header[2] == 0xFF;
        }
        else if (lowerContentType.Contains("png"))
        {
            return header[0] == 0x89 && header[1] == 0x50 && header[2] == 0x4E && header[3] == 0x47;
        }
        else if (lowerContentType.Contains("gif"))
        {
            return header[0] == 0x47 && header[1] == 0x49 && header[2] == 0x46;
        }
        else if (lowerContentType.Contains("webp"))
        {
            if (bytesRead < 12)
                return false;
            return header[0] == 0x52 && header[1] == 0x49 && header[2] == 0x46 && header[3] == 0x46 &&
                   header[8] == 0x57 && header[9] == 0x45 && header[10] == 0x42 && header[11] == 0x50;
        }

        return false;
    }

    /// <summary>
    /// Sanitizes filename to prevent path traversal attacks.
    /// </summary>
    public static string SanitizeFileName(string fileName)
    {
        if (string.IsNullOrWhiteSpace(fileName))
            throw new ArgumentException("Filename cannot be empty", nameof(fileName));

        var sanitized = Path.GetFileName(fileName);

        var invalidChars = Path.GetInvalidFileNameChars();
        sanitized = string.Join("_", sanitized.Split(invalidChars, StringSplitOptions.RemoveEmptyEntries));

        if (string.IsNullOrWhiteSpace(sanitized) || sanitized.All(c => c == '.'))
            throw new ArgumentException("Invalid filename", nameof(fileName));

        return sanitized;
    }
}
