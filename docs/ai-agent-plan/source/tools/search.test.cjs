"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const os=require("node:os");
const {spawnSync}=require("node:child_process");
const {DEFAULT_ROOT,UNKNOWN,loadLibrary,search,buildPrompt,checkCitations,yaml}=require("./library.cjs");
const library=loadLibrary();
function cli(...args){
  return spawnSync(process.execPath,[path.join(__dirname,"search.cjs"),...args],{cwd:os.tmpdir(),encoding:"utf8",timeout:10000});
}
function withCopy(fn){
  const directory=fs.mkdtempSync(path.join(os.tmpdir(),"mrbekox-source-test-"));
  fs.cpSync(DEFAULT_ROOT,directory,{recursive:true});
  try{return fn(directory);}finally{
    const resolved=path.resolve(directory);
    if(!resolved.startsWith(path.resolve(os.tmpdir())+path.sep)||!path.basename(resolved).startsWith("mrbekox-source-test-"))throw new Error("Test klasörü silme hedefi güvenli değil.");
    fs.rmSync(resolved,{recursive:true,force:true});
  }
}
test("30 birincil kaynak, 60 parça ve 23 aşama doğrulanır",()=>{
  assert.equal(library.manifest.sources.length,30);
  assert.equal(library.chunks.length,60);
  assert.equal(Object.keys(library.stageMap.stages).length,23);
  assert.equal(library.manifest.sources.filter(s=>s.type==="official").length,22);
  assert.equal(library.manifest.sources.filter(s=>s.type==="academic").length,4);
  assert.equal(library.manifest.sources.filter(s=>s.type==="engineering").length,4);
});
test("ACK sorusu B4 kapsamında doğru protokol kaynağını getirir",()=>{
  const r=search(library,{stage:"B4",query:"Consumer ACK ile publisher confirm arasındaki fark nedir?",top:4});
  assert.ok(r.matches.some(m=>m.source_id==="RMQ-CONFIRMS"));
  assert.ok(r.matches.every(m=>library.stageMap.stages.B4.sources.includes(m.source_id)));
  assert.equal(r.sufficiency,"not_assessed");
});
test("Pydantic ve routing soruları ilgili kaynaklara gider",()=>{
  const p=search(library,{stage:"A1",query:"Pydantic BaseModel veri doğrulama",top:2,type:"official"});
  assert.ok(p.matches.some(m=>m.source_id==="PYDANTIC-MODELS"));
  const r=search(library,{stage:"A5",query:"Soru karmaşıklığına göre mod seçimi ve koşullu yönlendirme",top:4});
  assert.ok(r.matches.some(m=>m.source_id==="LG-WORKFLOWS"));
});
test("Bilinmeyen konuya ilgisiz aşama kaynakları zorla eklenmez",()=>{
  const r=search(library,{stage:"A5",query:"kuantumzebra999 morfoloji777",top:6});
  assert.equal(r.retrieval_status,"no_match");
  assert.equal(r.context,"");
  const prompt=buildPrompt(library,r);
  assert.ok(prompt.includes("(İlgili kaynak parçası bulunamadı.)"));
  assert.ok(prompt.includes(UNKNOWN));
});
test("Prompt soru ve parçaları tek seferde güvenli yerleştirir",()=>{
  const question="Publisher confirms {retrieved_chunks} {user_question} $& nedir?";
  const r=search(library,{stage:"B3",query:question,top:2});
  const prompt=buildPrompt(library,r);
  assert.ok(prompt.includes("CONTEXT:\n["));
  assert.ok(prompt.endsWith("SORU:\n"+question+"\n"));
  assert.ok(prompt.includes("SADECE"));
});
test("Kaynak kimliği ve boş bağlam yanıtı denetimi çalışır",()=>{
  const r=search(library,{stage:"B4",query:"publisher confirms ACK",top:2});
  const id=r.matches[0].chunk_id;
  assert.equal(checkCitations(r,"Teknik bilgi. ["+id+"]").valid,true);
  assert.equal(checkCitations(r,"Teknik bilgi. [FAKE-SOURCE#C1]").valid,false);
  assert.equal(checkCitations(r,"Kaynak bulunmayan iddia.").valid,false);
  const empty=search(library,{query:"kuantumzebra999"});
  assert.equal(checkCitations(empty,UNKNOWN).valid,true);
  assert.equal(checkCitations(empty,"Bir cevap. ["+id+"]").valid,false);
});
test("Boyut ve kaynak türü sınırı tam parçalarla uygulanır",()=>{
  const r=search(library,{stage:"A7",query:"retrieval context research agent",top:20,maxChars:1500,type:"academic"});
  assert.ok(r.context.length<=1500);
  assert.ok(r.matches.every(m=>m.type==="academic"));
  assert.ok(r.matches.every(m=>r.context.includes("METİN: "+m.text)));
});
test("CLI farklı çalışma klasöründen JSON ve prompt üretir",()=>{
  const r=cli("search","--stage","B4","--query","Consumer ACK ve publisher confirms","--format","json");
  assert.equal(r.status,0,r.stderr);
  assert.ok(JSON.parse(r.stdout).matches.length>0);
  const p=cli("search","--stage","A5","--query","Koşullu yönlendirme","--format","prompt");
  assert.equal(p.status,0,p.stderr);
  assert.ok(p.stdout.includes("SORU:\nKoşullu yönlendirme"));
});
test("Hatalı aşama ve seçenekler açık hata döndürür",()=>{
  assert.equal(cli("search","--stage","A99","--query","routing").status,2);
  assert.equal(cli("search","--stage","A5","--query","routing","--top","0").status,2);
  assert.equal(cli("search","--query","routing","--query","state").status,2);
});
test("Değişen kaynak içeriği bütünlük kontrolünde reddedilir",()=>{
  withCopy(directory=>{
    const source=library.manifest.sources[0];
    fs.appendFileSync(path.join(directory,source.notes_file),"\nBeklenmeyen değişiklik.\n");
    assert.throws(()=>loadLibrary(directory),/hash/);
  });
});
test("JSON YAML drift ve arşiv dışı kaynak yolu reddedilir",()=>{
  withCopy(directory=>{
    fs.appendFileSync(path.join(directory,"manifest.yaml"),"# değişiklik\n");
    assert.throws(()=>loadLibrary(directory),/aynaları farklı/);
  });
  withCopy(directory=>{
    const file=path.join(directory,"manifest.json");
    const changed=JSON.parse(fs.readFileSync(file,"utf8"));
    changed.sources[0].notes_file="../../outside.md";
    fs.writeFileSync(file,JSON.stringify(changed,null,2)+"\n");
    fs.writeFileSync(path.join(directory,"manifest.yaml"),"# JSON dosyasından üretilen okunabilir YAML aynası.\n"+yaml(changed)+"\n");
    assert.throws(()=>loadLibrary(directory),/arşiv dışına/);
  });
});
