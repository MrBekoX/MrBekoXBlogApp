import Link from 'next/link';
import Image from 'next/image';
import { format } from 'date-fns';
import { tr } from 'date-fns/locale';
import { getImageUrl } from '@/lib/utils';
import type { BlogPost } from '@/types';
import { Card, CardContent, CardFooter, CardHeader } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar';
import { Calendar, Eye, ArrowRight, Clock } from 'lucide-react';

interface PostCardProps {
  post: BlogPost;
}

export function PostCard({ post }: PostCardProps) {
  const getInitials = (name: string) => {
    return name
      .split(' ')
      .map((n) => n[0])
      .join('')
      .toUpperCase()
      .slice(0, 2);
  };

  return (
    <Card className="group overflow-hidden transition-all duration-300 hover:shadow-xl hover:shadow-primary/5 border-border/50 bg-card/80 backdrop-blur-sm hover:border-primary/30">
      {post.featuredImageUrl && (
        <Link href={`/posts/${post.slug}`} className="block overflow-hidden">
          <div className="relative aspect-video overflow-hidden bg-muted">
            <Image
              src={getImageUrl(post.featuredImageUrl) ?? ''}
              alt={post.title}
              fill
              sizes="(max-width: 768px) 100vw, (max-width: 1200px) 50vw, 33vw"
              className="object-cover transition-transform duration-500 group-hover:scale-110"
              loading="lazy"
            />
          </div>
        </Link>
      )}

      <CardHeader className="space-y-3 pb-2">
        {/* Categories */}
        {post.categories && post.categories.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {post.categories.slice(0, 2).map((category) => (
              <Badge 
                key={category.id}
                variant="secondary" 
                className="bg-primary/10 text-primary border-0 font-medium"
              >
                {category.name}
              </Badge>
            ))}
          </div>
        )}

        {/* Title */}
        <Link href={`/posts/${post.slug}`} className="block group/title">
          <h2 className="line-clamp-2 text-xl font-semibold font-serif tracking-tight transition-colors group-hover/title:text-primary">
            {post.title}
          </h2>
        </Link>
      </CardHeader>

      <CardContent className="pb-4">
        <p className="line-clamp-3 text-muted-foreground leading-relaxed">
          {post.excerpt}
        </p>
      </CardContent>

      <CardFooter className="flex items-center justify-between pt-4 border-t border-border/50">
        {/* Author */}
        {post.author && (
          <div className="flex items-center gap-2">
            <Avatar className="h-8 w-8 ring-2 ring-background">
              <AvatarImage src={post.author.avatarUrl} alt={post.author.fullName} />
              <AvatarFallback className="text-xs bg-primary/10 text-primary font-medium">
                {getInitials(post.author.fullName || post.author.userName)}
              </AvatarFallback>
            </Avatar>
            <span className="text-sm font-medium">{post.author.fullName || post.author.userName}</span>
          </div>
        )}

        {/* Meta */}
        <div className="flex items-center gap-3 text-sm text-muted-foreground">
          <div className="flex items-center gap-1">
            <Calendar className="h-3.5 w-3.5" />
            <span>
              {format(new Date(post.publishedAt || post.createdAt), 'd MMM yyyy', { locale: tr })}
            </span>
          </div>
          {post.aiEstimatedReadingTime && (
            <div className="flex items-center gap-1">
              <Clock className="h-3.5 w-3.5" />
              <span>{post.aiEstimatedReadingTime} dk</span>
            </div>
          )}
          <div className="flex items-center gap-1">
            <Eye className="h-3.5 w-3.5" />
            <span>{post.viewCount}</span>
          </div>
        </div>
      </CardFooter>

      {/* Read more indicator */}
      <div className="absolute bottom-4 right-4 opacity-0 translate-x-2 group-hover:opacity-100 group-hover:translate-x-0 transition-all duration-300">
        <Link 
          href={`/posts/${post.slug}`}
          className="flex items-center gap-1 text-sm font-medium text-primary"
        >
          Devamını Oku
          <ArrowRight className="h-4 w-4" />
        </Link>
      </div>
    </Card>
  );
}
