'use client';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { ImageUpload } from '@/components/image-upload';
import type { FieldErrors, UseFormRegister } from 'react-hook-form';

interface FeaturedImageCardProps {
  value: string | undefined;
  onChange: (url: string) => void;
  disabled: boolean;
  register: UseFormRegister<{ featuredImageUrl?: string } & Record<string, unknown>>;
  errors: FieldErrors<{ featuredImageUrl?: string }>;
}

export function FeaturedImageCard({
  value,
  onChange,
  disabled,
  register,
  errors,
}: FeaturedImageCardProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Öne Çıkan Görsel</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <ImageUpload
          value={value || undefined}
          onChange={(url) => onChange(url || '')}
          disabled={disabled}
        />
        <div className="relative">
          <div className="absolute inset-0 flex items-center">
            <span className="w-full border-t" />
          </div>
          <div className="relative flex justify-center text-xs uppercase">
            <span className="bg-card px-2 text-muted-foreground">veya URL girin</span>
          </div>
        </div>
        <Input
          placeholder="Görsel URL'si"
          {...register('featuredImageUrl')}
        />
        {errors.featuredImageUrl && (
          <p className="text-sm text-destructive">{errors.featuredImageUrl.message}</p>
        )}
      </CardContent>
    </Card>
  );
}
