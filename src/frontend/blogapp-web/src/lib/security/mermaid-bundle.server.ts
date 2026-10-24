import { readFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { Buffer } from 'node:buffer';
import path from 'node:path';

// Only server route handlers import this loader. Both delivery modes use the
// same pinned, traced package bytes; chart data never becomes JavaScript.
let bundle: Promise<{ bytes: Uint8Array<ArrayBuffer>; etag: string }> | undefined;
let inlineBundle: Promise<string> | undefined;

export function loadMermaidBundle() {
  return bundle ??= readFile(path.join(process.cwd(), 'node_modules/mermaid/dist/mermaid.min.js')).then((buffer) => ({
    bytes: Uint8Array.from(buffer),
    etag: '"' + createHash('sha256').update(buffer).digest('hex') + '"',
  }));
}

export function loadInlineMermaidBundle() {
  return inlineBundle ??= loadMermaidBundle().then(({ bytes }) => Buffer.from(bytes).toString('base64'));
}
