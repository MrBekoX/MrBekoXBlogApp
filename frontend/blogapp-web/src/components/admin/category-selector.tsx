'use client';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import type { Category } from '@/types';

interface CategorySelectorProps {
  categories: Category[];
  selectedCategories: string[];
  onSelectionChange: (categories: string[]) => void;
}

export function CategorySelector({
  categories,
  selectedCategories,
  onSelectionChange,
}: CategorySelectorProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Kategori</CardTitle>
      </CardHeader>
      <CardContent>
        <Select
          value={selectedCategories[0] || ''}
          onValueChange={(value) => onSelectionChange(value ? [value] : [])}
        >
          <SelectTrigger>
            <SelectValue placeholder="Kategori seçin" />
          </SelectTrigger>
          <SelectContent>
            {categories.map((category) => (
              <SelectItem key={category.id} value={category.id}>
                {category.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </CardContent>
    </Card>
  );
}
