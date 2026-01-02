'use client';

import * as React from 'react';
import { useCallback, useState } from 'react';
import { Upload, X, Loader2, ImageIcon, AlertCircle } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { cn, getImageUrl } from '@/lib/utils';
import { mediaApi } from '@/lib/api';
import {
  validateImageFile,
  formatFileSize,
  MAX_FILE_SIZE_MB,
  ALLOWED_EXTENSIONS,
} from '@/lib/file-validation';
import { toast } from 'sonner';

interface ImageUploadProps {
  value?: string;
  onChange: (url: string | undefined) => void;
  disabled?: boolean;
  className?: string;
}

export function ImageUpload({ value, onChange, disabled, className }: ImageUploadProps) {
  const [isUploading, setIsUploading] = useState(false);
  const [isDragOver, setIsDragOver] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = React.useRef<HTMLInputElement>(null);

  const handleFile = useCallback(
    async (file: File) => {
      setError(null);

      // Validate file
      const validation = validateImageFile(file);
      if (!validation.isValid) {
        setError(validation.error || 'Geçersiz dosya');
        toast.error(validation.error || 'Geçersiz dosya');
        return;
      }

      setIsUploading(true);

      try {
        const response = await mediaApi.uploadImage(file);

        if (response.success && response.data) {
          onChange(response.data.url);
          toast.success('Görsel yüklendi');
        } else {
          const errorMsg = response.message || 'Görsel yüklenemedi';
          setError(errorMsg);
          toast.error(errorMsg);
        }
      } catch (err) {
        const errorMsg = err instanceof Error ? err.message : 'Görsel yüklenemedi';
        setError(errorMsg);
        toast.error(errorMsg);
      } finally {
        setIsUploading(false);
      }
    },
    [onChange]
  );

  const handleDrop = useCallback(
    (e: React.DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      setIsDragOver(false);

      if (disabled || isUploading) return;

      const file = e.dataTransfer.files[0];
      if (file) {
        handleFile(file);
      }
    },
    [disabled, isUploading, handleFile]
  );

  const handleDragOver = useCallback((e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragOver(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragOver(false);
  }, []);

  const handleInputChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) {
        handleFile(file);
      }
      // Reset input value to allow re-selecting the same file
      e.target.value = '';
    },
    [handleFile]
  );

  const handleRemove = useCallback(() => {
    onChange(undefined);
    setError(null);
  }, [onChange]);

  const handleClick = useCallback(() => {
    if (!disabled && !isUploading) {
      inputRef.current?.click();
    }
  }, [disabled, isUploading]);

  // If we have a value (URL), show the preview
  if (value) {
    return (
      <div className={cn('relative group', className)}>
        <div className="relative aspect-video rounded-lg overflow-hidden border bg-muted">
          <img
            src={getImageUrl(value)}
            alt="Öne çıkan görsel"
            className="w-full h-full object-cover"
          />
          <div className="absolute inset-0 bg-black/50 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center">
            <Button
              type="button"
              variant="destructive"
              size="sm"
              onClick={handleRemove}
              disabled={disabled}
            >
              <X className="h-4 w-4 mr-1" />
              Kaldır
            </Button>
          </div>
        </div>
        <p className="mt-2 text-xs text-muted-foreground truncate">{value}</p>
      </div>
    );
  }

  return (
    <div className={className}>
      <div
        onClick={handleClick}
        onDrop={handleDrop}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        className={cn(
          'relative flex flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed p-6 cursor-pointer transition-colors',
          isDragOver && 'border-primary bg-primary/5',
          error && 'border-destructive',
          disabled && 'opacity-50 cursor-not-allowed',
          !isDragOver && !error && 'border-muted-foreground/25 hover:border-muted-foreground/50'
        )}
      >
        <input
          ref={inputRef}
          type="file"
          accept={ALLOWED_EXTENSIONS.join(',')}
          onChange={handleInputChange}
          disabled={disabled || isUploading}
          className="sr-only"
        />

        {isUploading ? (
          <>
            <Loader2 className="h-10 w-10 text-muted-foreground animate-spin" />
            <p className="text-sm text-muted-foreground">Yükleniyor...</p>
          </>
        ) : error ? (
          <>
            <AlertCircle className="h-10 w-10 text-destructive" />
            <p className="text-sm text-destructive text-center">{error}</p>
            <Button type="button" variant="outline" size="sm" onClick={handleClick}>
              Tekrar Dene
            </Button>
          </>
        ) : (
          <>
            {isDragOver ? (
              <Upload className="h-10 w-10 text-primary" />
            ) : (
              <ImageIcon className="h-10 w-10 text-muted-foreground" />
            )}
            <div className="text-center">
              <p className="text-sm font-medium">
                {isDragOver ? 'Bırakın' : 'Görsel yüklemek için tıklayın veya sürükleyin'}
              </p>
              <p className="text-xs text-muted-foreground mt-1">
                JPEG, PNG, GIF, WebP (maks. {MAX_FILE_SIZE_MB}MB)
              </p>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
