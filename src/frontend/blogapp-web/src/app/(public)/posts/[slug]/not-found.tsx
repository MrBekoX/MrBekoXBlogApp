import Link from 'next/link';
import { ArrowLeft } from 'lucide-react';

export default function PostNotFound() {
  return (
    <div className="max-w-3xl font-mono py-16 text-center">
      <div className="text-6xl mb-6" style={{ fontFamily: "'VT323', monospace" }}>
        <span className="text-ide-primary">404</span>
      </div>
      <h1
        className="text-3xl text-white glow-text uppercase tracking-tight mb-4"
        style={{ fontFamily: "'VT323', monospace" }}
      >
        Yazı Bulunamadı
      </h1>
      <p className="text-sm text-gray-500 mb-8 max-w-md mx-auto">
        Aradığınız yazı mevcut değil veya kaldırılmış olabilir.
      </p>
      <Link
        href="/posts"
        className="inline-flex items-center gap-2 text-xs text-ide-primary hover:text-white border border-ide-primary/30 hover:border-ide-primary px-4 py-2 rounded transition-all"
      >
        <ArrowLeft className="w-3 h-3" />
        cd ../posts/
      </Link>
    </div>
  );
}
