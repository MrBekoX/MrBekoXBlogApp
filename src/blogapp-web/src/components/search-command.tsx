'use client';

import * as React from 'react';
import { useRouter } from 'next/navigation';
import {
  Command,
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command';
import { Search, FileText, Tag, Folder, Loader2, AlertCircle } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { postsApi, categoriesApi, tagsApi } from '@/lib/api';
import { toast } from 'sonner';
import type { BlogPost, Category, Tag as TagType } from '@/types';

// Minimum arama uzunluğu
const MIN_SEARCH_LENGTH = 2;
const DEBOUNCE_DELAY = 400;

export function SearchCommand() {
  const router = useRouter();
  const [open, setOpen] = React.useState(false);
  const [search, setSearch] = React.useState('');
  const [isLoading, setIsLoading] = React.useState(false);
  const [searchError, setSearchError] = React.useState<string | null>(null);
  const [posts, setPosts] = React.useState<BlogPost[]>([]);
  const [categories, setCategories] = React.useState<Category[]>([]);
  const [tags, setTags] = React.useState<TagType[]>([]);

  // Keyboard shortcut
  React.useEffect(() => {
    const down = (e: KeyboardEvent) => {
      if (e.key === 'k' && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        setOpen((open) => !open);
      }
    };

    document.addEventListener('keydown', down);
    return () => document.removeEventListener('keydown', down);
  }, []);

  // Search when query changes with debounce and minimum length
  React.useEffect(() => {
    const searchTerm = search.trim();
    
    // Minimum karakter kontrolü
    if (searchTerm.length > 0 && searchTerm.length < MIN_SEARCH_LENGTH) {
      setPosts([]);
      setCategories([]);
      setTags([]);
      return;
    }
    
    const searchData = async () => {
      if (!searchTerm) {
        setPosts([]);
        setCategories([]);
        setTags([]);
        return;
      }

      setIsLoading(true);
      setSearchError(null);
      try {
        // Backend'den arama sonuçlarını al - tüm filtreleme server-side yapılır
        const postsRes = await postsApi.getAll({ 
          search: searchTerm, 
          pageSize: 10, 
          status: 'Published' 
        });

        if (postsRes.success && postsRes.data) {
          setPosts(postsRes.data.items);
        } else {
          setPosts([]);
        }
        
        // Kategori ve tag'leri de backend'den al (arama terimine göre)
        const [categoriesRes, tagsRes] = await Promise.all([
          categoriesApi.getAll(),
          tagsApi.getAll(),
        ]);

        // Türkçe karakter uyumlu filtreleme
        const normalizeText = (text: string) => 
          text.toLowerCase()
            .replace(/ı/g, 'i')
            .replace(/İ/g, 'i')
            .replace(/ö/g, 'o')
            .replace(/Ö/g, 'o')
            .replace(/ü/g, 'u')
            .replace(/Ü/g, 'u')
            .replace(/ş/g, 's')
            .replace(/Ş/g, 's')
            .replace(/ğ/g, 'g')
            .replace(/Ğ/g, 'g')
            .replace(/ç/g, 'c')
            .replace(/Ç/g, 'c');
        
        const normalizedSearch = normalizeText(searchTerm);
        
        if (categoriesRes.success && categoriesRes.data) {
          setCategories(
            categoriesRes.data.filter((c) => {
              const normalizedName = normalizeText(c.name);
              return normalizedName.includes(normalizedSearch) || 
                     c.name.toLowerCase().includes(searchTerm.toLowerCase());
            }).slice(0, 3)
          );
        }
        if (tagsRes.success && tagsRes.data) {
          setTags(
            tagsRes.data.filter((t) => {
              const normalizedName = normalizeText(t.name);
              return normalizedName.includes(normalizedSearch) || 
                     t.name.toLowerCase().includes(searchTerm.toLowerCase());
            }).slice(0, 3)
          );
        }
      } catch (error) {
        console.error('Search error:', error);
        const errorMessage = 'Arama sırasında bir hata oluştu. Lütfen tekrar deneyin.';
        setSearchError(errorMessage);
        toast.error(errorMessage);
        setPosts([]);
        setCategories([]);
        setTags([]);
      } finally {
        setIsLoading(false);
      }
    };

    const debounce = setTimeout(searchData, DEBOUNCE_DELAY);
    return () => clearTimeout(debounce);
  }, [search]);

  const handleSelect = (type: 'post' | 'category' | 'tag', identifier: string) => {
    setOpen(false);
    setSearch('');

    switch (type) {
      case 'post':
        router.push(`/posts/${identifier}`);
        break;
      case 'category':
        router.push(`/posts?categoryId=${identifier}`);
        break;
      case 'tag':
        router.push(`/posts?tagId=${identifier}`);
        break;
    }
  };

  return (
    <>
      <Button
        variant="outline"
        size="sm"
        className="relative h-9 w-9 p-0 xl:h-9 xl:w-60 xl:justify-start xl:px-3 xl:py-2"
        onClick={() => setOpen(true)}
      >
        <Search className="h-4 w-4 xl:mr-2" />
        <span className="hidden xl:inline-flex">Search...</span>
        <kbd className="pointer-events-none absolute right-1.5 top-1.5 hidden h-6 select-none items-center gap-1 rounded border bg-muted px-1.5 font-mono text-[10px] font-medium opacity-100 xl:flex">
          <span className="text-xs">⌘</span>K
        </kbd>
      </Button>

      <CommandDialog open={open} onOpenChange={setOpen}>
        <CommandInput
          placeholder="Search posts, categories, tags..."
          value={search}
          onValueChange={setSearch}
        />
        <CommandList>
            {isLoading && (
              <div className="flex items-center justify-center py-6">
                <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
              </div>
            )}

            {!isLoading && !search.trim() && (
              <CommandEmpty className="py-6 text-center text-sm text-muted-foreground">
                Aramaya başlamak için yazmaya başlayın...
              </CommandEmpty>
            )}

            {!isLoading && search.trim().length > 0 && search.trim().length < MIN_SEARCH_LENGTH && (
              <CommandEmpty className="py-6 text-center text-sm text-muted-foreground">
                En az {MIN_SEARCH_LENGTH} karakter girin
              </CommandEmpty>
            )}

            {!isLoading && searchError && (
              <CommandEmpty className="py-6 text-center">
                <AlertCircle className="h-8 w-8 mx-auto text-destructive mb-2" />
                <p className="text-sm font-medium text-destructive">{searchError}</p>
              </CommandEmpty>
            )}

            {!isLoading && !searchError && search.trim().length >= MIN_SEARCH_LENGTH && posts.length === 0 && categories.length === 0 && tags.length === 0 && (
              <CommandEmpty className="py-6 text-center">
                <p className="text-sm font-medium">Böyle bir makale bulunamadı</p>
                <p className="text-xs text-muted-foreground mt-1">
                  &ldquo;{search.trim()}&rdquo; ile eşleşen sonuç yok
                </p>
              </CommandEmpty>
            )}

            {posts.length > 0 && (
              <CommandGroup heading="Posts">
                {posts.map((post) => (
                  <CommandItem
                    key={post.id}
                    value={post.title}
                    onSelect={() => handleSelect('post', post.slug)}
                    className="cursor-pointer"
                  >
                    <FileText className="mr-2 h-4 w-4" />
                    <div className="flex flex-col">
                      <span>{post.title}</span>
                      <span className="text-xs text-muted-foreground">
                        {post.excerpt?.slice(0, 60)}...
                      </span>
                    </div>
                  </CommandItem>
                ))}
              </CommandGroup>
            )}

            {categories.length > 0 && (
              <CommandGroup heading="Categories">
                {categories.map((category) => (
                  <CommandItem
                    key={category.id}
                    value={category.name}
                    onSelect={() => handleSelect('category', category.id)}
                    className="cursor-pointer"
                  >
                    <Folder className="mr-2 h-4 w-4" />
                    <span>{category.name}</span>
                    {category.postCount !== undefined && (
                      <span className="ml-auto text-xs text-muted-foreground">
                        {category.postCount} posts
                      </span>
                    )}
                  </CommandItem>
                ))}
              </CommandGroup>
            )}

            {tags.length > 0 && (
              <CommandGroup heading="Tags">
                {tags.map((tag) => (
                  <CommandItem
                    key={tag.id}
                    value={tag.name}
                    onSelect={() => handleSelect('tag', tag.id)}
                    className="cursor-pointer"
                  >
                    <Tag className="mr-2 h-4 w-4" />
                    <span>#{tag.name}</span>
                    {tag.postCount !== undefined && (
                      <span className="ml-auto text-xs text-muted-foreground">
                        {tag.postCount} posts
                      </span>
                    )}
                  </CommandItem>
                ))}
              </CommandGroup>
            )}
        </CommandList>
      </CommandDialog>
    </>
  );
}

