import Link from 'next/link';
import { Button } from '@/components/ui/button';
import { ArrowLeft, FileQuestion } from 'lucide-react';

export default function PostNotFound() {
  return (
    <div className="container max-w-4xl py-24 text-center">
      <div className="w-20 h-20 mx-auto mb-6 rounded-full bg-muted flex items-center justify-center">
        <FileQuestion className="w-10 h-10 text-muted-foreground" />
      </div>
      <h1 className="text-3xl font-bold mb-4">Yazı Bulunamadı</h1>
      <p className="text-muted-foreground mb-8 max-w-md mx-auto">
        Aradığınız yazı mevcut değil veya kaldırılmış olabilir.
      </p>
      <Button asChild>
        <Link href="/posts">
          <ArrowLeft className="mr-2 h-4 w-4" />
          Yazılara Dön
        </Link>
      </Button>
    </div>
  );
}
