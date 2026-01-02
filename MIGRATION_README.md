# 🔍 Arama Optimizasyonu Migration Rehberi

Bu rehber, PostgreSQL Full-Text Search optimizasyonlarını veritabanınıza uygulamanız için hazırlanmıştır.

## 📋 Önkoşullar

- PostgreSQL veritabanı çalışıyor olmalı
- Docker kullanıyorsanız: `docker-compose up -d` ile container'ları başlatın
- PostgreSQL client (psql) yüklü olmalı (opsiyonel)

---

## 🚀 Hızlı Başlangıç (Docker ile - ÖNERİLEN)

### Adım 1: PowerShell'i açın

Proje kök dizininde (`D:\MrBekoXBlogApp`) PowerShell'i açın.

### Adım 2: Script'i çalıştırın

```powershell
.\run-search-migration.ps1
```

Bu script otomatik olarak:
- ✅ Container'ın çalışıp çalışmadığını kontrol eder
- ✅ SQL dosyasını container'a kopyalar
- ✅ Migration'ı uygular
- ✅ Geçici dosyaları temizler

---

## 🔧 Manuel Yöntemler

### Yöntem 1: Docker Container İçinde

```powershell
# Container'a bağlan
docker exec -it blogapp-postgres psql -U blogapp_user -d blogdb_dev

# SQL script'i çalıştır (psql içinde)
\i /tmp/SearchOptimization.sql

# VEYA dosyayı kopyalayıp çalıştır
docker cp src\BlogApp.Server\BlogApp.Server.Infrastructure\Persistence\Migrations\SearchOptimization.sql blogapp-postgres:/tmp/
docker exec -i blogapp-postgres psql -U blogapp_user -d blogdb_dev -f /tmp/SearchOptimization.sql
```

### Yöntem 2: Doğrudan psql ile (PostgreSQL Client Yüklüyse)

```powershell
cd src\BlogApp.Server\BlogApp.Server.Infrastructure\Persistence\Migrations

psql -h localhost -p 5432 -U blogapp_user -d blogdb_dev -f SearchOptimization.sql
```

**Şifre:** `K9mP2@xQ4!nR7&wT57` (Development ortamı için)

### Yöntem 3: pgAdmin veya DBeaver ile

1. pgAdmin/DBeaver'ı açın
2. Veritabanına bağlanın:
   - **Host:** localhost
   - **Port:** 5432
   - **Database:** blogdb_dev
   - **Username:** blogapp_user
   - **Password:** K9mP2@xQ4!nR7&wT57
3. `SearchOptimization.sql` dosyasını açın
4. Tüm script'i seçip çalıştırın (F5 veya Execute)

---

## ✅ Migration Sonrası Kontrol

Migration'ın başarılı olduğunu kontrol etmek için:

```sql
-- Extension'ları kontrol et
SELECT * FROM pg_extension WHERE extname = 'pg_trgm';

-- Index'leri kontrol et
SELECT indexname, indexdef 
FROM pg_indexes 
WHERE tablename = 'posts' 
AND indexname LIKE '%search%' OR indexname LIKE '%trgm%';

-- Search vector kolonunu kontrol et
SELECT column_name, data_type 
FROM information_schema.columns 
WHERE table_name = 'posts' 
AND column_name = 'search_vector';

-- Trigger'ı kontrol et
SELECT trigger_name, event_manipulation, event_object_table
FROM information_schema.triggers
WHERE trigger_name = 'posts_search_vector_trigger';
```

---

## 🐛 Sorun Giderme

### Hata: "container is not running"
```powershell
# Container'ı başlat
docker-compose up -d postgres
```

### Hata: "permission denied"
```powershell
# Container içinde superuser olarak çalıştır
docker exec -it blogapp-postgres psql -U postgres -d blogdb_dev -f /tmp/SearchOptimization.sql
```

### Hata: "extension pg_trgm does not exist"
Bu normal, script zaten extension'ı oluşturur. Hata mesajını görmezden gelebilirsiniz.

### Hata: "relation already exists"
Bazı index'ler zaten varsa, script `IF NOT EXISTS` kullandığı için güvenle çalıştırabilirsiniz.

---

## 📊 Migration İçeriği

Bu migration şunları ekler:

1. **pg_trgm Extension** - ILIKE performansı için
2. **search_vector Kolonu** - Full-Text Search için
3. **GIN Index'ler** - Hızlı arama için
4. **Trigram Index'ler** - Türkçe karakter uyumu için
5. **Otomatik Trigger** - Yeni kayıtlar için otomatik güncelleme
6. **Composite Index'ler** - Sık kullanılan sorgular için

---

## 🎯 Sonraki Adımlar

Migration başarılı olduktan sonra:

1. ✅ Uygulamayı yeniden başlatın
2. ✅ Arama fonksiyonunu test edin
3. ✅ Performans iyileşmesini gözlemleyin

**Not:** Production ortamında migration yapmadan önce mutlaka backup alın!

