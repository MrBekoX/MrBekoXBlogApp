import { ImageResponse } from 'next/og';

export const runtime = 'edge';
export const alt = 'MrBekoX Blog - Backend, Yazılım Mimarisi & AI';
export const size = {
  width: 1200,
  height: 630,
};
export const contentType = 'image/png';

export default async function Image() {
  return new ImageResponse(
    (
      <div
        style={{
          height: '100%',
          width: '100%',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          backgroundColor: '#0a0a0a',
          backgroundImage: 'radial-gradient(circle at 25% 25%, rgba(139, 92, 246, 0.15) 0%, transparent 50%), radial-gradient(circle at 75% 75%, rgba(59, 130, 246, 0.15) 0%, transparent 50%)',
        }}
      >
        <div
          style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 24,
          }}
        >
          <div
            style={{
              fontSize: 72,
              fontWeight: 'bold',
              background: 'linear-gradient(to right, #8b5cf6, #3b82f6)',
              backgroundClip: 'text',
              color: 'transparent',
              display: 'flex',
            }}
          >
            MrBekoX
          </div>
          <div
            style={{
              fontSize: 36,
              color: '#a1a1aa',
              textAlign: 'center',
              maxWidth: 800,
              display: 'flex',
            }}
          >
            Backend Geliştirme, Yazılım Mimarisi & AI
          </div>
        </div>
        <div
          style={{
            position: 'absolute',
            bottom: 40,
            display: 'flex',
            alignItems: 'center',
            gap: 12,
            color: '#71717a',
            fontSize: 24,
          }}
        >
          <span>📚</span>
          <span>Teknik Blog</span>
        </div>
      </div>
    ),
    {
      ...size,
    }
  );
}
