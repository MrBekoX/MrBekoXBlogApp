"use strict";
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const DEFAULT_ROOT = path.resolve(__dirname, "..");
const UNKNOWN = "Bu konuda elimde yeterli bilgi yok";
const SOURCE_TYPES = ["official", "academic", "engineering"];
function sha256(value) { return crypto.createHash("sha256").update(value).digest("hex"); }
function yaml(value, indent = 0) {
  const pad = " ".repeat(indent);
  if (Array.isArray(value)) {
    if (!value.some(v => v && typeof v === "object")) return pad + JSON.stringify(value);
    return value.map(v => {
      const lines = yaml(v, indent + 2).split("\n");
      return pad + "- " + lines[0].trimStart() + (lines.length > 1 ? "\n" + lines.slice(1).join("\n") : "");
    }).join("\n");
  }
  if (value && typeof value === "object") return Object.entries(value).map(([key, v]) => {
    if (v && typeof v === "object" && (!Array.isArray(v) || v.some(x => x && typeof x === "object"))) return pad + key + ":\n" + yaml(v, indent + 2);
    return pad + key + ": " + JSON.stringify(v);
  }).join("\n");
  return pad + JSON.stringify(value);
}
function safeFile(root, relative) {
  if (typeof relative !== "string" || path.isAbsolute(relative)) throw new Error("Kaynak yolu göreli olmalıdır.");
  const resolved = path.resolve(root, relative);
  if (!resolved.startsWith(path.resolve(root) + path.sep)) throw new Error("Kaynak yolu arşiv dışına çıkıyor.");
  const realRoot = fs.realpathSync(root);
  const realFile = fs.realpathSync(resolved);
  if (!realFile.startsWith(realRoot + path.sep)) throw new Error("Kaynak bağlantısı arşiv dışına çıkıyor.");
  return resolved;
}
function loadLibrary(root = DEFAULT_ROOT) {
  root = path.resolve(root);
  const manifest = JSON.parse(fs.readFileSync(path.join(root, "manifest.json"), "utf8"));
  const stageMap = JSON.parse(fs.readFileSync(path.join(root, "stage-map.json"), "utf8"));
  for (const [name, value] of [["manifest", manifest], ["stage-map", stageMap]]) {
    const generated = "# JSON dosyasından üretilen okunabilir YAML aynası.\n" + yaml(value) + "\n";
    if (fs.readFileSync(path.join(root, name + ".yaml"), "utf8") !== generated) throw new Error(name + " JSON ve YAML aynaları farklı.");
  }
  if (manifest.schema_version !== 1 || stageMap.schema_version !== 1) throw new Error("Desteklenmeyen arşiv sürümü.");
  if (manifest.sources.length !== manifest.source_count) throw new Error("Kaynak sayısı tutarsız.");
  const ids = new Set();
  const urls = new Set();
  const chunks = [];
  for (const source of manifest.sources) {
    if (!/^[A-Z][A-Z0-9-]+$/.test(source.id) || ids.has(source.id)) throw new Error("Geçersiz veya tekrarlı kaynak kimliği.");
    ids.add(source.id);
    const url = new URL(source.url);
    if (url.protocol !== "https:" || urls.has(source.url)) throw new Error("Kaynak URL'si HTTPS ve benzersiz olmalıdır.");
    urls.add(source.url);
    if (!SOURCE_TYPES.includes(source.type)) throw new Error("Bilinmeyen kaynak türü.");
    if (!source.last_verified_on || !source.version_scope || !source.publisher) throw new Error("Kaynak metadata'sı eksik.");
    const file = safeFile(root, source.notes_file);
    const text = fs.readFileSync(file, "utf8");
    if (sha256(text) !== source.notes_sha256) throw new Error("Kaynak notu hash'i değişmiş: " + source.id + ". İçeriği inceleyip metadata'yı yeniden üretin.");
    const snapshot = JSON.parse(fs.readFileSync(safeFile(root, source.snapshot_file), "utf8"));
    if (snapshot.source_id !== source.id || snapshot.notes_sha256 !== source.notes_sha256 || snapshot.kind !== "curated_reference_notes") throw new Error("Snapshot kaydı tutarsız: " + source.id);
    const matches = [...text.matchAll(/^## (C\d+) (.+)\r?\n([\s\S]*?)(?=^## |$(?![\s\S]))/gm)];
    if (!matches.length) throw new Error("Aranabilir parça bulunamadı: " + source.id);
    const chunkIds = new Set();
    for (const match of matches) {
      if (chunkIds.has(match[1])) throw new Error("Tekrarlı parça kimliği.");
      chunkIds.add(match[1]);
      chunks.push({id:source.id + "#" + match[1], source, heading:match[2], text:match[3].trim(), file});
    }
  }
  for (const [stage, info] of Object.entries(stageMap.stages)) {
    if (!/^[AB]\d+$/.test(stage) || !info.query || !Array.isArray(info.sources) || !info.sources.length) throw new Error("Geçersiz aşama eşlemesi.");
    for (const id of info.sources) if (!ids.has(id)) throw new Error("Aşama bilinmeyen kaynağa bağlı: " + id);
  }
  return {root, manifest, stageMap, chunks};
}
function normalize(value) {
  return String(value).toLocaleLowerCase("tr-TR").normalize("NFKD").replace(/\p{M}/gu, "").replace(/ı/g, "i");
}
const STOP = new Set(normalize("ve veya ile bir bu şu için gibi nasıl nedir ne neden hangi göre hakkında olarak olan olsun mı mi mu mü the a an and or of to in is are how what why").split(" "));
function tokenize(value) { return (normalize(value).match(/[\p{L}\p{N}_]+/gu) || []).filter(t => t.length > 1 && !STOP.has(t)); }
const GROUPS = [
  ["ack","acknowledgement","acknowledgements","onay","teslim"],
  ["confirm","confirms","confirmation","publisher"],
  ["router","routing","yonlendirme","conditional","kosullu","karmasiklik","karmasikligi","karmasikligina","karmasik","complexity","mod"],
  ["checkpoint","kalicilik","persistence","state","durum"],
  ["cancel","cancellation","iptal","iptali","iptalinde","iptalini"],
  ["resume","surdurme","devam"],
  ["retrieval","retrieve","arama","aramasi","getir","getirme"],
  ["source","kaynak","kaynaklar","kaynagi","kanit"],
  ["validation","validate","dogrulama","dogrulamak"],
  ["duplicate","duplicates","tekrar","tekrarli","idempotent","idempotency"],
  ["progress","ilerleme","streaming"],
  ["transaction","transactional","islem","commit","outbox"],
  ["context","baglam","baglami","baglamdan"],
  ["cache","onbellek"]
];
function expandedTokens(value) {
  const original = [...new Set(tokenize(value))];
  const expanded = new Set(original);
  for (const group of GROUPS) if (group.some(t => original.includes(t))) group.forEach(t => expanded.add(t));
  return {original, expanded:[...expanded]};
}
function search(library, options) {
  const query = String(options.query || "").trim();
  if (!query) throw new Error("Arama sorusu boş olamaz.");
  if (query.length > 8000) throw new Error("Arama sorusu en fazla 8000 karakter olabilir.");
  const stage = options.stage ? String(options.stage).toUpperCase() : null;
  if (stage && !library.stageMap.stages[stage]) throw new Error("Bilinmeyen aşama: " + stage);
  const type = options.type || null;
  if (type && !SOURCE_TYPES.includes(type)) throw new Error("Bilinmeyen kaynak türü.");
  const top = Number(options.top ?? 6);
  const maxChars = Number(options.maxChars ?? 12000);
  if (!Number.isInteger(top) || top < 1 || top > 20) throw new Error("Top değeri 1–20 arasında olmalıdır.");
  if (!Number.isInteger(maxChars) || maxChars < 600 || maxChars > 60000) throw new Error("CONTEXT boyutu 600–60000 karakter arasında olmalıdır.");
  const stageIds = stage ? new Set(library.stageMap.stages[stage].sources) : null;
  const corpus = library.chunks.filter(c => (!stageIds || stageIds.has(c.source.id)) && (!type || c.source.type === type));
  const queryTokens = expandedTokens(query);
  if (!queryTokens.original.length) return result(query, stage, [], maxChars);
  const docs = corpus.map(chunk => {
    const tokens = tokenize(chunk.heading + " " + chunk.text);
    const frequencies = new Map();
    for (const token of tokens) frequencies.set(token, (frequencies.get(token) || 0) + 1);
    return {chunk, frequencies, length:Math.max(tokens.length, 1), meta:new Set(tokenize(chunk.source.title + " " + chunk.source.tags.join(" ") + " " + chunk.source.technology.join(" ")))};
  });
  const avgLength = docs.reduce((n,d) => n+d.length,0) / Math.max(docs.length,1);
  const df = new Map();
  for (const term of queryTokens.expanded) df.set(term, docs.filter(d => d.frequencies.has(term)).length);
  const ranked = docs.map(doc => {
    let score = 0;
    const matched = [];
    for (const term of queryTokens.expanded) {
      const tf = doc.frequencies.get(term) || 0;
      const weight = queryTokens.original.includes(term) ? 1 : 0.32;
      if (tf) {
        const idf = Math.log(1 + (docs.length - df.get(term) + 0.5)/(df.get(term)+0.5));
        score += weight * idf * tf * 2.2 / (tf + 1.2*(0.25 + 0.75*doc.length/avgLength));
      }
      if (doc.meta.has(term)) score += weight * 0.7;
      if (tf || doc.meta.has(term)) matched.push(term);
    }
    score *= doc.chunk.source.type === "official" ? 1.08 : 1;
    return {chunk:doc.chunk, score, matched};
  }).filter(r => r.score > 0).sort((a,b) => b.score-a.score || a.chunk.id.localeCompare(b.chunk.id));
  const counts = new Map();
  const chosen = [];
  let characters = 0;
  for (const candidate of ranked) {
    if (chosen.length >= top) break;
    if ((counts.get(candidate.chunk.source.id)||0) >= 2) continue;
    const block = contextBlock(candidate.chunk);
    if (characters + block.length + 2 > maxChars) continue;
    chosen.push({...candidate, block});
    characters += block.length + 2;
    counts.set(candidate.chunk.source.id, (counts.get(candidate.chunk.source.id)||0)+1);
  }
  return result(query, stage, chosen, maxChars);
}
function contextBlock(chunk) {
  const s = chunk.source;
  return [
    "[" + chunk.id + "]",
    "KAYNAK: " + s.title,
    "URL: " + s.url,
    "TÜR: " + s.type,
    "YAZAR/YAYINCI: " + s.authors.join(", ") + " / " + s.publisher,
    "SÜRÜM KAPSAMI: " + s.version_scope,
    "KONTROL TARİHİ: " + s.last_verified_on,
    "METİN TÜRÜ: Kaynağa dayalı, editoryal olarak hazırlanmış kısa not; tam sayfa kopyası değildir.",
    "BÖLÜM: " + chunk.heading,
    "METİN: " + chunk.text
  ].join("\n");
}
function result(query, stage, candidates, maxChars) {
  const context = candidates.map(c => c.block).join("\n\n");
  return {
    schema_version:1, query, stage,
    retrieval_status:candidates.length ? "matched" : "no_match",
    sufficiency:"not_assessed",
    retrieval_method:"local_bm25_with_metadata_and_bilingual_keywords",
    max_context_chars:maxChars,
    context,
    matches:candidates.map(c => ({chunk_id:c.chunk.id,source_id:c.chunk.source.id,title:c.chunk.source.title,url:c.chunk.source.url,type:c.chunk.source.type,heading:c.chunk.heading,text:c.chunk.text,notes_file:c.chunk.source.notes_file,last_verified_on:c.chunk.source.last_verified_on,version_scope:c.chunk.source.version_scope,score:Number(c.score.toFixed(5)),matched_terms:c.matched})),
    if_insufficient:UNKNOWN
  };
}
function buildPrompt(library, retrieved) {
  const template = fs.readFileSync(path.join(library.root, "prompts", "rag-grounded.md"), "utf8");
  const context = retrieved.context || "(İlgili kaynak parçası bulunamadı.)";
  return template.replace(/\{(retrieved_chunks|user_question)\}/g, (_,key) => key === "retrieved_chunks" ? context : retrieved.query);
}
function checkCitations(retrieved, answer) {
  const text=String(answer).trim();
  const allowed=new Set(retrieved.matches.map(m=>m.chunk_id));
  if (text === UNKNOWN || text === UNKNOWN + ".") return {valid:true,checks:["insufficient_context_response"],semantic_support:"not_assessed"};
  const found=[...text.matchAll(/\[([A-Z][A-Z0-9-]*#C\d+)\]/g)].map(m=>m[1]);
  const issues=[];
  if(!allowed.size) issues.push("Boş CONTEXT için yalnız yetersiz bilgi yanıtı kabul edilir.");
  if(!text) issues.push("Yanıt boş.");
  if(!found.length) issues.push("Yanıtta kaynak kimliği yok.");
  for(const id of new Set(found)) if(!allowed.has(id)) issues.push("CONTEXT dışında kaynak kimliği: "+id);
  const paragraphs=text.split(/\n\s*\n/).filter(p=>p.trim());
  paragraphs.forEach((p,i)=>{ if(!/\[[A-Z][A-Z0-9-]*#C\d+\]/.test(p)) issues.push("Paragraf "+(i+1)+" için kaynak yok."); });
  return {valid:issues.length===0,issues,semantic_support:"not_assessed",note:"Bu kontrol kaynak kimliklerini ve paragraf işaretlerini doğrular; iddiaların anlamsal olarak desteklendiğini garanti etmez."};
}
module.exports={DEFAULT_ROOT,UNKNOWN,SOURCE_TYPES,sha256,yaml,loadLibrary,search,buildPrompt,checkCitations,normalize,tokenize};
