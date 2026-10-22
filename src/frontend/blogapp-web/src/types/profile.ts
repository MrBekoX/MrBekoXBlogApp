/**
 * Yayımlanmış yazar profili (GET /api/v1/profile → ApiResponse<AuthorProfile>).
 * Backend aktif + public + hash doğrulanmış profili döner; kullanılamıyorsa 503.
 * İstemci tarafı normalizasyonu: lib/author-profile.ts (toleranslı, güvenli).
 */

export interface AuthorProfileClaim {
  asOf?: string | null;
  /** current_at_source | historical | dated_snapshot */
  temporal?: string | null;
  status?: string | null;
}

export interface AuthorProfileSection {
  /** Kararlı bölüm kimliği = /about anchor'ı. */
  sectionId: string;
  anchor: string;
  kind: string;
  headingPath: string[];
  title: string;
  /** Markdown, birinci şahıs Türkçe (ham kaynak dili). */
  body: string;
  notes: string[];
  claim?: AuthorProfileClaim | null;
}

export interface AuthorProfileContactChannel {
  kind: string;
  label: string;
  url: string;
}

export interface AuthorProfile {
  profileId: string;
  revision: number;
  contentHash: string;
  language: string;
  ownerName: string;
  status: string;
  sections: AuthorProfileSection[];
  contactChannels: AuthorProfileContactChannel[];
}
