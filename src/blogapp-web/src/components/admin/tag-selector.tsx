'use client';

import { useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { X } from 'lucide-react';
import type { Tag } from '@/types';

/**
 * Tag ismini temizler - XSS ve injection saldırılarını önler.
 */
function sanitizeTagName(tag: string): string {
  return tag
    .trim()
    .replace(/[\x00-\x1F\x7F]/g, '')           // Kontrol karakterlerini kaldır
    .replace(/[<>"'&`\\;(){}[\]]/g, '')          // HTML/JS tehlikeli karakterleri kaldır
    .replace(/javascript\s*:/gi, '')             // javascript: protocol
    .replace(/on\w+\s*=/gi, '')                  // onerror=, onclick= vb.
    .replace(/\s+/g, ' ')                        // Çoklu boşlukları normalize et
    .slice(0, 50);                               // Max 50 karakter
}

interface TagSelectorProps {
  tags: Tag[];
  selectedTags: string[];
  onSelectionChange: (tags: string[]) => void;
}

export function TagSelector({
  tags,
  selectedTags,
  onSelectionChange,
}: TagSelectorProps) {
  const [newTag, setNewTag] = useState('');

  const handleAddTag = () => {
    const sanitized = sanitizeTagName(newTag);
    if (sanitized && !selectedTags.includes(sanitized)) {
      onSelectionChange([...selectedTags, sanitized]);
      setNewTag('');
    }
  };

  const handleRemoveTag = (tag: string) => {
    onSelectionChange(selectedTags.filter((t) => t !== tag));
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Etiketler</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap gap-2">
          {selectedTags.map((tag) => (
            <Badge key={tag} variant="secondary" className="gap-1">
              {tag}
              <button
                type="button"
                onClick={() => handleRemoveTag(tag)}
                className="ml-1 hover:text-destructive"
              >
                <X className="h-3 w-3" />
              </button>
            </Badge>
          ))}
        </div>
        <div className="flex gap-2">
          <Select
            value=""
            onValueChange={(value) => {
              if (value && !selectedTags.includes(value)) {
                onSelectionChange([...selectedTags, value]);
              }
            }}
          >
            <SelectTrigger className="flex-1">
              <SelectValue placeholder="Etiket seçin" />
            </SelectTrigger>
            <SelectContent>
              {tags
                .filter((tag) => !selectedTags.includes(tag.name))
                .map((tag) => (
                  <SelectItem key={tag.id} value={tag.name}>
                    {tag.name}
                  </SelectItem>
                ))}
            </SelectContent>
          </Select>
        </div>
        <div className="flex gap-2">
          <Input
            placeholder="Yeni etiket ekle"
            value={newTag}
            onChange={(e) => setNewTag(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault();
                handleAddTag();
              }
            }}
          />
          <Button type="button" variant="outline" onClick={handleAddTag}>
            Ekle
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
