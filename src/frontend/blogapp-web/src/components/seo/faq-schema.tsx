import { FAQPage, WithContext } from 'schema-dts';
import { JsonLd } from './json-ld';

interface FAQItem {
  question: string;
  answer: string;
}

interface FAQSchemaProps {
  items: FAQItem[];
}

/**
 * FAQPage JSON-LD schema — AI arama motorlarinda 3.2x daha fazla gorunurluk.
 * Minimum 1, maksimum 5 soru-cevap cifti kabul eder.
 */
export function FAQSchema({ items }: FAQSchemaProps) {
  if (items.length === 0) return null;

  const faqSchema: WithContext<FAQPage> = {
    '@context': 'https://schema.org',
    '@type': 'FAQPage',
    mainEntity: items.slice(0, 5).map((item) => ({
      '@type': 'Question' as const,
      name: item.question,
      acceptedAnswer: {
        '@type': 'Answer' as const,
        text: item.answer,
      },
    })),
  };

  return <JsonLd data={faqSchema} />;
}

/**
 * Markdown iceriginden FAQ cikarir.
 * Soru isareti iceren H2/H3 basliklarini soru olarak alir,
 * baslik altindaki ilk paragrafi cevap olarak kullanir.
 * Soru isareti olmayan basliklardan "X nedir?" formatinda soru turetir.
 */
export function extractFAQFromContent(content: string): FAQItem[] {
  const lines = content.split('\n');
  const faqs: FAQItem[] = [];

  for (let i = 0; i < lines.length && faqs.length < 5; i++) {
    const line = lines[i].trim();

    // H2 veya H3 baslik mi?
    const headingMatch = line.match(/^#{2,3}\s+(.+)$/);
    if (!headingMatch) continue;

    const heading = headingMatch[1].trim();

    // Baslik altindaki ilk paragraf (bos olmayan ilk satir blogu)
    let answer = '';
    for (let j = i + 1; j < lines.length; j++) {
      const nextLine = lines[j].trim();

      // Baska bir basliga veya ayiriciya ulastik
      if (nextLine.startsWith('#') || nextLine.startsWith('---')) break;

      // Bos satir — eger cevap zaten varsa dur
      if (nextLine === '') {
        if (answer) break;
        continue;
      }

      // Kod blogu ici — atla
      if (nextLine.startsWith('```')) {
        let closingFound = false;
        for (let k = j + 1; k < lines.length; k++) {
          if (lines[k].trim().startsWith('```')) {
            j = k;
            closingFound = true;
            break;
          }
        }
        if (!closingFound) break; // acik kod blogu — bu basligi atla
        if (answer) break;
        continue;
      }

      // Markdown formatting temizle
      const cleanLine = nextLine
        .replace(/\*\*(.+?)\*\*/g, '$1')  // bold
        .replace(/\*(.+?)\*/g, '$1')       // italic
        .replace(/`(.+?)`/g, '$1')         // inline code
        .replace(/\[(.+?)\]\(.+?\)/g, '$1') // links
        .replace(/^[-*]\s+/, '');           // list markers

      answer += (answer ? ' ' : '') + cleanLine;
    }

    // Cevap cok kisa veya yok — atla
    if (answer.length < 20) continue;

    // Cevabi 300 karakterle sinirla
    if (answer.length > 300) {
      answer = answer.substring(0, 297) + '...';
    }

    // Soru formatini belirle
    let question: string;
    if (heading.includes('?')) {
      question = heading;
    } else {
      // Basliktan soru turet
      question = `${heading} nedir?`;
    }

    faqs.push({ question, answer });
  }

  return faqs;
}
