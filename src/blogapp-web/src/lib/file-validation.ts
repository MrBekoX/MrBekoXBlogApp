/**
 * Dosya validasyon yardımcı fonksiyonları
 * Backend ile senkronize kurallar
 */

// İzin verilen görsel tipleri (backend ile aynı)
export const ALLOWED_IMAGE_TYPES = [
  'image/jpeg',
  'image/png',
  'image/gif',
  'image/webp',
] as const;

// İzin verilen uzantılar
export const ALLOWED_EXTENSIONS = ['.jpg', '.jpeg', '.png', '.gif', '.webp'] as const;

// Maksimum dosya boyutu: 10MB (backend ile aynı)
export const MAX_FILE_SIZE = 10 * 1024 * 1024;

// Maksimum dosya boyutu (okunabilir format)
export const MAX_FILE_SIZE_MB = 10;

export type AllowedImageType = (typeof ALLOWED_IMAGE_TYPES)[number];

export interface FileValidationResult {
  isValid: boolean;
  error?: string;
}

/**
 * Dosya tipini kontrol eder
 */
export function validateFileType(file: File): FileValidationResult {
  const isValidType = ALLOWED_IMAGE_TYPES.includes(file.type as AllowedImageType);

  if (!isValidType) {
    return {
      isValid: false,
      error: `Geçersiz dosya tipi. İzin verilenler: JPEG, PNG, GIF, WebP`,
    };
  }

  return { isValid: true };
}

/**
 * Dosya uzantısını kontrol eder
 */
export function validateFileExtension(file: File): FileValidationResult {
  const extension = '.' + file.name.split('.').pop()?.toLowerCase();
  const isValidExtension = ALLOWED_EXTENSIONS.includes(extension as typeof ALLOWED_EXTENSIONS[number]);

  if (!isValidExtension) {
    return {
      isValid: false,
      error: `Geçersiz dosya uzantısı. İzin verilenler: ${ALLOWED_EXTENSIONS.join(', ')}`,
    };
  }

  return { isValid: true };
}

/**
 * Dosya boyutunu kontrol eder
 */
export function validateFileSize(file: File): FileValidationResult {
  if (file.size > MAX_FILE_SIZE) {
    return {
      isValid: false,
      error: `Dosya çok büyük. Maksimum boyut: ${MAX_FILE_SIZE_MB}MB`,
    };
  }

  return { isValid: true };
}

/**
 * Dosyayı tam olarak doğrular (tip, uzantı, boyut)
 */
export function validateImageFile(file: File): FileValidationResult {
  // Tip kontrolü
  const typeResult = validateFileType(file);
  if (!typeResult.isValid) return typeResult;

  // Uzantı kontrolü
  const extensionResult = validateFileExtension(file);
  if (!extensionResult.isValid) return extensionResult;

  // Boyut kontrolü
  const sizeResult = validateFileSize(file);
  if (!sizeResult.isValid) return sizeResult;

  return { isValid: true };
}

/**
 * Dosya boyutunu okunabilir formata çevirir
 */
export function formatFileSize(bytes: number): string {
  if (bytes === 0) return '0 B';

  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));

  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

/**
 * Dosya tipine göre ikon belirler
 */
export function getFileTypeIcon(contentType: string): string {
  switch (contentType) {
    case 'image/jpeg':
      return '🖼️';
    case 'image/png':
      return '🖼️';
    case 'image/gif':
      return '🎞️';
    case 'image/webp':
      return '🖼️';
    default:
      return '📄';
  }
}
