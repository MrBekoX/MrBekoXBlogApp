/** Only fixed trusted code is embedded. Chart text travels through postMessage, never HTML or URLs. */
export function mermaidRendererDocument(nonce: string, version: string, inlineBundle?: string): string {
  if (!/^[A-Za-z0-9+/]+={0,2}$/.test(nonce) || !/^[A-Za-z0-9._-]+$/.test(version)) throw new Error('Invalid renderer metadata.');
  if (inlineBundle !== undefined && !/^[A-Za-z0-9+/]+={0,2}$/.test(inlineBundle)) throw new Error('Invalid trusted bundle encoding.');
  const loadScript = inlineBundle === undefined
    ? '<script nonce="' + nonce + '" src="/mermaid-renderer/mermaid.js?v=' + version + '"></script>'
    : '<script nonce="' + nonce + '">(() => { const script = document.createElement("script");'
      + 'script.nonce = document.currentScript.nonce;'
      + 'script.textContent = new TextDecoder().decode(Uint8Array.from(atob(' + JSON.stringify(inlineBundle) + '), character => character.charCodeAt(0)));'
      + 'document.head.appendChild(script); })();</script>';
  return '<!doctype html><html><head><meta charset="utf-8"><style>html,body{margin:0;padding:0;width:1024px}</style></head><body>'
    + loadScript
    + '<script nonce="' + nonce + '">' + RENDERER_SCRIPT + '</script></body></html>';
}

const RENDERER_SCRIPT = String.raw`
(() => {
  const token = location.hash.slice(1);
  if (!/^[a-f0-9]{32}$/.test(token) || parent === window) return;
  let started = false;
  addEventListener('message', async (event) => {
    const data = event.data;
    if (event.source !== parent || !data || data.token !== token || data.type !== 'mermaid:render' || started) return;
    if (typeof data.chart !== 'string' || data.chart.length > 500000 || !['dark', 'default'].includes(data.theme)) return;
    started = true;
    try {
      mermaid.initialize({ startOnLoad: false, securityLevel: 'strict', suppressErrorRendering: true, theme: data.theme });
      await mermaid.parse(data.chart);
      const result = await mermaid.render('isolated-diagram', data.chart);
      parent.postMessage({ type: 'mermaid:result', token, svg: result.svg }, '*');
    } catch (error) {
      parent.postMessage({ type: 'mermaid:error', token, message: String(error?.message ?? error).split('\n')[0].slice(0, 400) }, '*');
    }
  });
  parent.postMessage({ type: 'mermaid:ready', token }, '*');
})();
`;
