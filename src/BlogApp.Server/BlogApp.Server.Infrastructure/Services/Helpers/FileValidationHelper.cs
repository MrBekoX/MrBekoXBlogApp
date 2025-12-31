namespace BlogApp.Server.Infrastructure.Services.Helpers;

/// <summary>
/// Provides file validation utilities including magic byte verification,
/// extension validation, and security checks.
/// </summary>
public static class FileValidationHelper
{
    /// <summary>
    /// Magic bytes (file signatures) for supported image formats.
    /// These are the first bytes of valid files that identify the file type.
    /// </summary>
    private static readonly Dictionary<string, byte[][]> ImageMagicBytes = new()
    {
        // JPEG: FFD8FF
        ["image/jpeg"] = [
            [0xFF, 0xD8, 0xFF]
        ],
        // PNG: 89504E47 0D0A1A0A
        ["image/png"] = [
            [0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]
        ],
        // GIF: GIF87a or GIF89a
        ["image/gif"] = [
            [0x47, 0x49, 0x46, 0x38, 0x37, 0x61], // GIF87a
            [0x47, 0x49, 0x46, 0x38, 0x39, 0x61]  // GIF89a
        ],
        // WebP: RIFF....WEBP
        ["image/webp"] = [
            [0x52, 0x49, 0x46, 0x46] // RIFF (first 4 bytes, WEBP at offset 8)
        ]
    };

    /// <summary>
    /// Extension to MIME type mapping for allowed image types.
    /// </summary>
    private static readonly Dictionary<string, string> ExtensionToMimeType = new(StringComparer.OrdinalIgnoreCase)
    {
        [".jpg"] = "image/jpeg",
        [".jpeg"] = "image/jpeg",
        [".png"] = "image/png",
        [".gif"] = "image/gif",
        [".webp"] = "image/webp"
    };

    /// <summary>
    /// Validates that the file content matches the expected image type.
    /// </summary>
    /// <param name="stream">The file stream to validate</param>
    /// <param name="fileName">The original filename</param>
    /// <param name="claimedContentType">The content type claimed by the upload</param>
    /// <returns>Validation result with error message if invalid</returns>
    public static async Task<FileValidationResult> ValidateImageAsync(
        Stream stream,
        string fileName,
        string claimedContentType)
    {
        var extension = Path.GetExtension(fileName)?.ToLowerInvariant();

        // 1. Validate extension is allowed
        if (string.IsNullOrEmpty(extension) || !ExtensionToMimeType.ContainsKey(extension))
        {
            return FileValidationResult.Invalid($"File extension '{extension}' is not allowed.");
        }

        // 2. Validate extension matches claimed content type
        var expectedMimeType = ExtensionToMimeType[extension];
        if (!string.Equals(expectedMimeType, claimedContentType, StringComparison.OrdinalIgnoreCase))
        {
            return FileValidationResult.Invalid($"Content type mismatch: extension suggests '{expectedMimeType}' but claimed '{claimedContentType}'.");
        }

        // 3. Read magic bytes from file
        var magicBytesBuffer = new byte[16];
        var originalPosition = stream.Position;

        try
        {
            stream.Position = 0;
            var bytesRead = await stream.ReadAsync(magicBytesBuffer);

            if (bytesRead < 3)
            {
                return FileValidationResult.Invalid("File too small to be a valid image.");
            }

            // 4. Validate magic bytes match claimed content type
            if (!ValidateMagicBytes(magicBytesBuffer, claimedContentType))
            {
                return FileValidationResult.Invalid("File content does not match claimed image type (magic bytes validation failed).");
            }

            // 5. Special validation for WebP (check WEBP signature at offset 8)
            if (claimedContentType == "image/webp" && bytesRead >= 12)
            {
                if (magicBytesBuffer[8] != 0x57 || // W
                    magicBytesBuffer[9] != 0x45 || // E
                    magicBytesBuffer[10] != 0x42 || // B
                    magicBytesBuffer[11] != 0x50)   // P
                {
                    return FileValidationResult.Invalid("Invalid WebP file format.");
                }
            }

            return FileValidationResult.Valid();
        }
        finally
        {
            // Reset stream position for subsequent processing
            stream.Position = originalPosition;
        }
    }

    /// <summary>
    /// Validates that the file's magic bytes match the expected content type.
    /// </summary>
    private static bool ValidateMagicBytes(byte[] fileBytes, string contentType)
    {
        if (!ImageMagicBytes.TryGetValue(contentType, out var signatures))
        {
            return false;
        }

        foreach (var signature in signatures)
        {
            if (fileBytes.Length >= signature.Length)
            {
                var matches = true;
                for (var i = 0; i < signature.Length; i++)
                {
                    if (fileBytes[i] != signature[i])
                    {
                        matches = false;
                        break;
                    }
                }
                if (matches) return true;
            }
        }

        return false;
    }

    /// <summary>
    /// Sanitizes a filename by removing potentially dangerous characters.
    /// </summary>
    public static string SanitizeFileName(string fileName)
    {
        var extension = Path.GetExtension(fileName);
        var baseName = Path.GetFileNameWithoutExtension(fileName);

        // Remove all characters except alphanumeric, dash, and underscore
        baseName = new string(baseName
            .Where(c => char.IsLetterOrDigit(c) || c == '-' || c == '_')
            .ToArray());

        // Ensure base name is not empty
        if (string.IsNullOrWhiteSpace(baseName))
        {
            baseName = "file";
        }

        // Limit filename length to prevent issues
        if (baseName.Length > 100)
        {
            baseName = baseName[..100];
        }

        return baseName + extension.ToLowerInvariant();
    }
}

/// <summary>
/// Result of file validation.
/// </summary>
public record FileValidationResult
{
    public bool IsValid { get; init; }
    public string? ErrorMessage { get; init; }

    public static FileValidationResult Valid() => new() { IsValid = true };
    public static FileValidationResult Invalid(string errorMessage) => new() { IsValid = false, ErrorMessage = errorMessage };
}
