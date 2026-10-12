#!/usr/bin/env node
"use strict";
const fs=require("node:fs");
const path=require("node:path");
const {DEFAULT_ROOT,sha256,yaml,loadLibrary}=require("./library.cjs");
try{
  const manifestPath=path.join(DEFAULT_ROOT,"manifest.json");
  const manifest=JSON.parse(fs.readFileSync(manifestPath,"utf8"));
  for(const source of manifest.sources){
    const file=path.resolve(DEFAULT_ROOT,source.notes_file);
    if(!file.startsWith(DEFAULT_ROOT+path.sep))throw new Error("Not yolu arşiv dışına çıkıyor.");
    const text=fs.readFileSync(file,"utf8");
    source.notes_sha256=sha256(text);
    source.chunk_count=(text.match(/^## C\d+ /gm)||[]).length;
    if(!source.chunk_count)throw new Error("Kaynak parçası yok: "+source.id);
    const snapshotPath=path.resolve(DEFAULT_ROOT,source.snapshot_file);
    if(!snapshotPath.startsWith(DEFAULT_ROOT+path.sep))throw new Error("Snapshot yolu arşiv dışına çıkıyor.");
    fs.writeFileSync(snapshotPath,JSON.stringify({source_id:source.id,url:source.url,checked_on:source.last_verified_on,kind:"curated_reference_notes",original_page_cached:false,original_content_sha256:null,notes_file:source.notes_file,notes_sha256:source.notes_sha256},null,2)+"\n","utf8");
  }
  manifest.source_count=manifest.sources.length;
  fs.writeFileSync(manifestPath,JSON.stringify(manifest,null,2)+"\n","utf8");
  for(const name of ["manifest","stage-map"]){
    const value=JSON.parse(fs.readFileSync(path.join(DEFAULT_ROOT,name+".json"),"utf8"));
    fs.writeFileSync(path.join(DEFAULT_ROOT,name+".yaml"),"# JSON dosyasından üretilen okunabilir YAML aynası.\n"+yaml(value)+"\n","utf8");
  }
  const checked=loadLibrary();
  console.log(JSON.stringify({sources:checked.manifest.sources.length,chunks:checked.chunks.length,verification_dates_changed:false}));
}catch(error){console.error("Hata: "+error.message);process.exitCode=2;}
