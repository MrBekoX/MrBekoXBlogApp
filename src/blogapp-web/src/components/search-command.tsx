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
import { Search, FileText, Tag, Folder, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { postsApi, categoriesApi, tagsApi } from '@/lib/api';
import type { BlogPost, Category, Tag as TagType } from '@/types';

export function SearchCommand() {
  const router = useRouter();
  const [open, setOpen] = React.useState(false);
  const [search, setSearch] = React.useState('');
  const [isLoading, setIsLoading] = React.useState(false);
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

  // Search when query changes
  React.useEffect(() => {
    const searchData = async () => {
      if (!search.trim()) {
        setPosts([]);
        return;
      }

      setIsLoading(true);
      try {
        const [postsRes, categoriesRes, tagsRes] = await Promise.all([
          postsApi.getAll({ search, pageSize: 5, status: 'Published' }),
          categoriesApi.getAll(),
          tagsApi.getAll(),
        ]);

        if (postsRes.success && postsRes.data) {
          setPosts(postsRes.data.items);
        }
        if (categoriesRes.success && categoriesRes.data) {
          setCategories(
            categoriesRes.data.filter((c) =>
              c.name.toLowerCase().includes(search.toLowerCase())
            ).slice(0, 3)
          );
        }
        if (tagsRes.success && tagsRes.data) {
          setTags(
            tagsRes.data.filter((t) =>
              t.name.toLowerCase().includes(search.toLowerCase())
            ).slice(0, 3)
          );
        }
      } catch (error) {
        console.error('Search error:', error);
      } finally {
        setIsLoading(false);
      }
    };

    const debounce = setTimeout(searchData, 300);
    return () => clearTimeout(debounce);
  }, [search]);

  const handleSelect = (type: 'post' | 'category' | 'tag', slug: string) => {
    setOpen(false);
    setSearch('');
    
    switch (type) {
      case 'post':
        router.push(`/posts/${slug}`);
        break;
      case 'category':
        router.push(`/categories/${slug}`);
        break;
      case 'tag':
        router.push(`/tags/${slug}`);
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

            {!isLoading && !search && (
              <CommandEmpty className="py-6 text-center text-sm text-muted-foreground">
                Start typing to search...
              </CommandEmpty>
            )}

            {!isLoading && search && posts.length === 0 && categories.length === 0 && tags.length === 0 && (
              <CommandEmpty>No results found.</CommandEmpty>
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
                    onSelect={() => handleSelect('category', category.slug)}
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
                    onSelect={() => handleSelect('tag', tag.slug)}
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

