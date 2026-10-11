#!/usr/bin/env node
"use strict";
const fs=require("node:fs");
const path=require("node:path");
const {DEFAULT_ROOT,loadLibrary,search,buildPrompt,checkCitations}=require("./library.cjs");
function usage(){
  return [
    "Kaynak arama ve RAG prompt hazırlama aracı — Node.js 18+, harici bağımlılık yok.",
    "",
    "node source/tools/search.cjs search --stage A5 --query \"Koşullu yönlendirme nasıl yapılır?\" --format prompt",
    "node source/tools/search.cjs search --stage B4 --query \"Consumer ACK ne zaman verilir?\" --format json",
    "node source/tools/search.cjs list --stage A7",
    "node source/tools/search.cjs verify",
    "node source/tools/search.cjs check-citations --context-json context.json --answer-file answer.txt",
    "",
    "Search seçenekleri: --query, --question-file, --stage, --type official|academic|engineering,",
    "                   --top 1..20, --max-context-chars 600..60000, --format text|json|context|prompt,",
    "                   --output dosya, --overwrite, --root kaynak-klasörü.",
    "Sonuç eşleşmesi, sorunun cevaplanabilir olduğu garantisini vermez."
  ].join("\n");
}
function args(argv){
  const command=argv[0]||"help";
  const values={};
  for(let i=1;i<argv.length;i++){
    const key=argv[i];
    if(!key.startsWith("--"))throw new Error("Beklenmeyen argüman: "+key);
    if(key==="--overwrite"){values.overwrite=true;continue;}
    if(i+1>=argv.length||argv[i+1].startsWith("--"))throw new Error("Seçenek değeri eksik: "+key);
    const allowed=["--query","--question-file","--stage","--type","--top","--max-context-chars","--format","--output","--root","--context-json","--answer-file"];
    if(!allowed.includes(key))throw new Error("Bilinmeyen seçenek: "+key);
    if(values[key]!==undefined)throw new Error("Seçenek tekrarlandı: "+key);
    values[key]=argv[++i];
  }
  return {command,values};
}
function saveOrPrint(text,values){
  if(values["--output"]){
    const file=path.resolve(values["--output"]);
    if(fs.existsSync(file)&&!values.overwrite)throw new Error("Dosya zaten var; üzerine yazmak için --overwrite gerekli.");
    fs.mkdirSync(path.dirname(file),{recursive:true});
    fs.writeFileSync(file,text+"\n","utf8");
    process.stderr.write("Yazıldı: "+file+"\n");
  }else process.stdout.write(text+"\n");
}
function main(argv){
  const {command,values}=args(argv);
  if(command==="help"){process.stdout.write(usage()+"\n");return;}
  if(!["search","list","verify","check-citations"].includes(command))throw new Error("Bilinmeyen komut: "+command);
  const library=loadLibrary(values["--root"]||DEFAULT_ROOT);
  let output;
  if(command==="search"){
    if(values["--query"]&&values["--question-file"])throw new Error("Query ve question-file birlikte kullanılamaz.");
    const question=values["--question-file"]?fs.readFileSync(path.resolve(values["--question-file"]),"utf8"):values["--query"];
    const retrieved=search(library,{query:question,stage:values["--stage"],type:values["--type"],top:values["--top"],maxChars:values["--max-context-chars"]});
    const format=values["--format"]||"text";
    if(format==="json")output=JSON.stringify(retrieved,null,2);
    else if(format==="context")output=retrieved.context||"(İlgili kaynak parçası bulunamadı.)";
    else if(format==="prompt")output=buildPrompt(library,retrieved);
    else if(format==="text")output=retrieved.matches.length?retrieved.matches.map(m=>"["+m.chunk_id+"] "+m.title+"\n"+m.url+"\n"+m.text).join("\n\n"):"İlgili kaynak parçası bulunamadı. "+retrieved.if_insufficient;
    else throw new Error("Bilinmeyen çıktı biçimi.");
  }else if(command==="list"){
    const stage=values["--stage"]?.toUpperCase();
    if(stage&&!library.stageMap.stages[stage])throw new Error("Bilinmeyen aşama.");
    if(values["--type"]&&!["official","academic","engineering"].includes(values["--type"]))throw new Error("Bilinmeyen kaynak türü.");
    const ids=stage?new Set(library.stageMap.stages[stage].sources):null;
    const selected=library.manifest.sources.filter(s=>(!ids||ids.has(s.id))&&(!values["--type"]||s.type===values["--type"]));
    output=values["--format"]==="json"?JSON.stringify(selected,null,2):selected.map(s=>s.id+" | "+s.type+" | "+s.title+"\n"+s.url).join("\n\n");
  }else if(command==="verify"){
    output=JSON.stringify({valid:true,sources:library.manifest.sources.length,chunks:library.chunks.length,stages:Object.keys(library.stageMap.stages).length,checks:["metadata","source_paths","note_hashes","snapshot_records","stage_links","json_yaml_sync"]},null,2);
  }else{
    if(!values["--context-json"]||!values["--answer-file"])throw new Error("Context JSON ve answer-file gerekli.");
    const context=JSON.parse(fs.readFileSync(path.resolve(values["--context-json"]),"utf8"));
    const answer=fs.readFileSync(path.resolve(values["--answer-file"]),"utf8");
    const checked=checkCitations(context,answer);
    output=JSON.stringify(checked,null,2);
    if(!checked.valid)process.exitCode=1;
  }
  saveOrPrint(output,values);
}
try{main(process.argv.slice(2));}catch(error){process.stderr.write("Hata: "+error.message+"\n");process.exitCode=2;}
