import type { Metadata } from 'next';
import Link from 'next/link';
import { ArrowLeft, ExternalLink } from 'lucide-react';
import { fetchAuthorProfile } from '@/lib/server-api';
import { datedClaimAsOf, formatProfileDate } from '@/lib/author-profile';
import { AUTHOR_NAME, OG_IMAGE_PATH, SITE_NAME, SITE_URL } from '@/lib/site-config';
import { ProfileAgentPanel } from '@/components/agent/profile-agent-panel';
import { ProfileMarkdown } from '@/components/profile/profile-markdown';
import { BreadcrumbSchema } from '@/components/seo/breadcrumb-schema';

/**
 * /about — yayımlanmış yazar profili + makalesiz Who am I asistanı.
 *
 * Profil gövdesi HER İSTEKTE backend GET /api/v1/profile'dan (aktif + public +
 * hash doğrulanmış sürüm; fetch no-store) sunucu tarafında okunur. Kullanılamazsa
 * biyografi gövdesi HTML'e hiç girmez (istemci tarafı sonradan kontrol yok).
 * force-dynamic: build zamanında backend gerekmez ve sayfa statik önbelleğe
 * alınmaz; HTML Cache-Control no-store (next.config.ts) + staleTimes.dynamic=0.
 */
export const dynamic = 'force-dynamic';

const PAGE_TITLE = `Who am I · ${AUTHOR_NAME}`;
const PAGE_DESCRIPTION =
  `${AUTHOR_NAME} hakkında yayımlanmış profil bilgileri ve bu profile dayanarak cevap veren Who am I asistanı.`;

export const metadata: Metadata = {
  title: PAGE_TITLE,
  description: PAGE_DESCRIPTION,
  openGraph: {
    title: `${PAGE_TITLE} | ${SITE_NAME} Blog`,
    description: PAGE_DESCRIPTION,
    url: `${SITE_URL}/about`,
    type: 'profile',
    images: [{ url: OG_IMAGE_PATH, width: 1200, height: 630, alt: PAGE_TITLE }],
  },
  twitter: {
    card: 'summary_large_image',
    title: `${PAGE_TITLE} | ${SITE_NAME} Blog`,
    description: PAGE_DESCRIPTION,
    images: [OG_IMAGE_PATH],
  },
  alternates: {
    canonical: `${SITE_URL}/about`,
  },
};

export default async function AboutPage() {
  const profile = await fetchAuthorProfile();

  return (
    <article className="max-w-3xl font-mono">
      <Link
        href="/"
        className="mb-8 inline-flex items-center gap-2 text-xs text-gray-500 transition-colors hover:text-ide-primary"
      >
        <ArrowLeft className="h-3 w-3" />
        <span>cd ~/</span>
      </Link>

      <header className="mb-8 space-y-3">
        <h1
          className="glow-text text-3xl uppercase leading-tight tracking-tight text-white md:text-4xl"
          style={{ fontFamily: "'VT323', monospace" }}
        >
          {PAGE_TITLE}
        </h1>
        {profile ? (
          <>
            <p className="text-sm leading-relaxed text-gray-400">
              Yazarın kendi anlatımıyla yayımlanmış profil bilgileri. Aşağıdaki asistan
              cevaplarını yalnız bu bölümlere dayandırır ve kaynak olarak ilgili bölüme bağlar.
            </p>
            {profile.contactChannels.length > 0 && (
              <ul className="flex flex-wrap gap-2" aria-label="Yayımlanmış iletişim kanalları">
                {profile.contactChannels.map((channel) => (
                  <li key={`${channel.kind}-${channel.url}`}>
                    <a
                      href={channel.url}
                      target="_blank"
                      rel="noopener noreferrer nofollow"
                      className="inline-flex items-center gap-1.5 rounded border border-ide-border px-2 py-1 text-xs text-gray-300 transition-colors hover:border-ide-primary hover:text-ide-primary"
                    >
                      <ExternalLink className="h-3 w-3" aria-hidden="true" />
                      {channel.label}
                    </a>
                  </li>
                ))}
              </ul>
            )}
            <p className="text-[10px] text-gray-600">
              Profil sürümü r{profile.revision} · {profile.contentHash.slice(0, 12)}
            </p>
          </>
        ) : null}
      </header>

      {profile ? (
        <>
          <section aria-label="Who am I asistanı" className="mb-10">
            <ProfileAgentPanel profileId={profile.profileId} />
          </section>

          <nav aria-label="Profil bölümleri" className="mb-10 rounded border border-ide-border/60 bg-black/20 p-4">
            <p className="mb-2 text-[10px] font-bold uppercase tracking-widest text-gray-500">{'// İçindekiler'}</p>
            <ol className="grid gap-1 text-xs sm:grid-cols-2">
              {profile.sections.map((section) => (
                <li key={section.sectionId}>
                  <a href={`#${section.sectionId}`} className="text-gray-400 transition-colors hover:text-ide-primary">
                    {section.title}
                  </a>
                </li>
              ))}
            </ol>
          </nav>

          <div className="space-y-10">
            {profile.sections.map((section) => {
              const asOf = datedClaimAsOf(section.claim);
              const titleId = `profile-section-${section.sectionId}-title`;
              const parentPath = section.headingPath.slice(0, -1);
              return (
                <section
                  key={section.sectionId}
                  id={section.sectionId}
                  aria-labelledby={titleId}
                  className="scroll-mt-6 border-t border-ide-border/40 pt-6"
                >
                  {parentPath.length > 0 && (
                    <p className="mb-1 text-[10px] uppercase tracking-widest text-gray-600">
                      {parentPath.join(' / ')}
                    </p>
                  )}
                  <h2 id={titleId} className="mb-3 text-lg text-white">
                    <a href={`#${section.sectionId}`} className="transition-colors hover:text-ide-primary">
                      {section.title}
                    </a>
                  </h2>
                  {asOf && (
                    <p className="mb-2 text-[11px] text-amber-400/80">
                      {formatProfileDate(asOf)} tarihli beyan; güncel durum farklı olabilir.
                    </p>
                  )}
                  {section.body.trim() && <ProfileMarkdown content={section.body} />}
                  {section.notes.length > 0 && (
                    <aside
                      aria-label="Notlar"
                      className="mt-3 space-y-1 border-l-2 border-ide-border pl-3 text-[11px] leading-snug text-gray-500"
                    >
                      {section.notes.map((note, index) => (
                        <p key={index}>{note}</p>
                      ))}
                    </aside>
                  )}
                </section>
              );
            })}
          </div>
        </>
      ) : (
        <div
          role="status"
          className="rounded border border-amber-500/30 bg-amber-500/5 p-4 text-sm text-amber-300"
          data-testid="profile-unavailable"
        >
          <p>Profil bilgileri şu an kullanılamıyor.</p>
          <p className="mt-1 text-xs text-gray-500">Lütfen daha sonra tekrar deneyin.</p>
        </div>
      )}

      <BreadcrumbSchema
        items={[
          { name: 'Ana Sayfa', url: '/' },
          { name: PAGE_TITLE, url: '/about' },
        ]}
      />
    </article>
  );
}
