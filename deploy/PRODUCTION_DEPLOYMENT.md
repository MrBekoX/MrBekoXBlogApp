# 🚀 Production Deployment Rehberi - Arama Optimizasyonu

Bu rehber, arama optimizasyonu değişikliklerini production ortamına güvenli bir şekilde uygulamanız için hazırlanmıştır.

---

## 📋 Pre-Deployment Checklist

### 1. Backup Alın (KRİTİK!)

```bash
# PostgreSQL backup
docker exec blogapp-postgres-prod pg_dump -U blogapp_user -d blogdb > backup_$(date +%Y%m%d_%H%M%S).sql

# VEYA Docker volume backup
docker run --rm -v blogapp_postgres_data:/data -v $(pwd):/backup alpine tar czf /backup/postgres_backup_$(date +%Y%m%d_%H%M%S).tar.gz /data
```

### 2. Maintenance Window Planlayın

- **Önerilen süre:** 15-30 dakika
- **Downtime:** Minimal (sadece database migration sırasında kısa bir süre)
- **En iyi zaman:** Düşük trafik saatleri

### 3. Test Ortamında Doğrulayın

- [ ] Tüm değişiklikler test ortamında çalışıyor
- [ ] Arama fonksiyonu test edildi
- [ ] Türkçe karakter aramaları test edildi
- [ ] Performans iyileştirmeleri gözlemlendi

---

## 🔧 Deployment Adımları

### Adım 1: Kod Değişikliklerini Deploy Edin

#### 1.1 Backend (API) Deployment

```bash
# Sunucuya bağlanın
ssh user@your-server

# Proje dizinine gidin
cd /path/to/BlogApp/deploy

# Git'ten en son değişiklikleri çekin
git pull origin main

# Docker image'ları rebuild edin (veya CI/CD pipeline kullanıyorsanız otomatik)
cd ../src/BlogApp.Server/BlogApp.Server.Api
docker build -t mrbeko/blog-app:api-latest .

# Frontend image'ı rebuild edin
cd ../../blogapp-web
docker build -t mrbeko/blog-app:web-latest .
```

#### 1.2 Container'ları Güncelleyin

```bash
cd /path/to/BlogApp/deploy

# Container'ları durdurun (zero-downtime için rolling update yapabilirsiniz)
docker-compose -f docker-compose.prod.yml down

# VEYA sadece API ve Frontend'i güncelleyin (PostgreSQL çalışmaya devam eder)
docker-compose -f docker-compose.prod.yml up -d --no-deps --build api frontend
```

---

### Adım 2: Database Migration (KRİTİK!)

#### 2.1 Production Migration Script'i Hazırlayın

Production için özel bir script oluşturun:

```bash
# Production migration script'ini oluşturun
cat > /tmp/prod-migration.sh << 'EOF'
#!/bin/bash
set -e

echo "Starting production database migration..."

# Container adı
CONTAINER_NAME="blogapp-postgres-prod"
DB_NAME="${POSTGRES_DB:-blogdb}"
DB_USER="${POSTGRES_USER:-blogapp_user}"

# SQL dosyasını container'a kopyala
docker cp SearchOptimization.sql ${CONTAINER_NAME}:/tmp/

# Migration'ı çalıştır
docker exec -i ${CONTAINER_NAME} psql -U ${DB_USER} -d ${DB_NAME} -f /tmp/SearchOptimization.sql

# Geçici dosyayı temizle
docker exec ${CONTAINER_NAME} rm /tmp/SearchOptimization.sql

echo "Migration completed successfully!"
EOF

chmod +x /tmp/prod-migration.sh
```

#### 2.2 Migration'ı Çalıştırın

```bash
# SQL dosyasını production sunucuya kopyalayın
scp src/BlogApp.Server/BlogApp.Server.Infrastructure/Persistence/Migrations/SearchOptimization.sql user@your-server:/tmp/

# Sunucuda migration script'ini çalıştırın
ssh user@your-server
cd /tmp
# .env dosyasından değişkenleri yükle
source /path/to/BlogApp/deploy/.env
./prod-migration.sh
```

#### 2.3 Alternatif: Manuel Migration

```bash
# Sunucuda
cd /path/to/BlogApp/deploy

# SQL dosyasını container'a kopyala
docker cp ../src/BlogApp.Server/BlogApp.Server.Infrastructure/Persistence/Migrations/SearchOptimization.sql blogapp-postgres-prod:/tmp/

# Migration'ı çalıştır
docker exec -i blogapp-postgres-prod psql -U blogapp_user -d blogdb -f /tmp/SearchOptimization.sql

# Kontrol et
docker exec -i blogapp-postgres-prod psql -U blogapp_user -d blogdb -c "\d posts" | grep search_vector
```

---

### Adım 3: Migration Sonrası Kontroller

```bash
# Extension'ı kontrol et
docker exec -i blogapp-postgres-prod psql -U blogapp_user -d blogdb -c "SELECT * FROM pg_extension WHERE extname = 'pg_trgm';"

# Index'leri kontrol et
docker exec -i blogapp-postgres-prod psql -U blogapp_user -d blogdb -c "SELECT indexname FROM pg_indexes WHERE tablename = 'posts' AND (indexname LIKE '%search%' OR indexname LIKE '%trgm%');"

# Search vector kolonunu kontrol et
docker exec -i blogapp-postgres-prod psql -U blogapp_user -d blogdb -c "SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'posts' AND column_name = 'search_vector';"

# Trigger'ı kontrol et
docker exec -i blogapp-postgres-prod psql -U blogapp_user -d blogdb -c "SELECT trigger_name FROM information_schema.triggers WHERE trigger_name = 'posts_search_vector_trigger';"
```

---

### Adım 4: Uygulamayı Başlatın

```bash
cd /path/to/BlogApp/deploy

# Tüm servisleri başlat
docker-compose -f docker-compose.prod.yml up -d

# Log'ları kontrol et
docker-compose -f docker-compose.prod.yml logs -f api
```

---

## ✅ Post-Deployment Validation

### 1. Health Check

```bash
# API health check
curl https://your-domain.com/api/v1/health

# Frontend kontrol
curl -I https://your-domain.com
```

### 2. Arama Fonksiyonunu Test Edin

- [ ] Basit arama çalışıyor mu?
- [ ] Türkçe karakter aramaları çalışıyor mu? (ş, ğ, ü, ö, ç, ı, İ)
- [ ] Debounce çalışıyor mu? (400ms gecikme)
- [ ] Minimum 2 karakter kontrolü çalışıyor mu?
- [ ] Empty state mesajı görünüyor mu?
- [ ] Relevance sıralaması doğru mu? (title > tags > category)

### 3. Performans Kontrolü

```bash
# API response time'ı ölçün
time curl "https://your-domain.com/api/v1/posts?search=test&pageSize=20"

# Database query performance
docker exec -i blogapp-postgres-prod psql -U blogapp_user -d blogdb -c "EXPLAIN ANALYZE SELECT * FROM posts WHERE \"Title\" ILIKE '%test%';"
```

---

## 🔄 Rollback Planı

Eğer bir sorun olursa:

### 1. Kod Rollback

```bash
# Önceki versiyona geri dön
git checkout <previous-commit-hash>

# Container'ları rebuild ve restart
docker-compose -f docker-compose.prod.yml up -d --build
```

### 2. Database Rollback (Gerekirse)

```bash
# Backup'tan geri yükle
docker exec -i blogapp-postgres-prod psql -U blogapp_user -d blogdb < backup_YYYYMMDD_HHMMSS.sql

# VEYA sadece migration'ı geri al
docker exec -i blogapp-postgres-prod psql -U blogapp_user -d blogdb << EOF
DROP TRIGGER IF EXISTS posts_search_vector_trigger ON posts;
DROP FUNCTION IF EXISTS posts_search_vector_update();
ALTER TABLE posts DROP COLUMN IF EXISTS search_vector;
DROP INDEX IF EXISTS IX_posts_search_vector;
DROP INDEX IF EXISTS IX_posts_title_trgm;
DROP INDEX IF EXISTS IX_posts_content_trgm;
DROP INDEX IF EXISTS IX_posts_excerpt_trgm;
DROP INDEX IF EXISTS IX_posts_slug_trgm;
EOF
```

---

## 📊 Monitoring ve Alerting

### 1. Log Monitoring

```bash
# API log'larını izle
docker-compose -f docker-compose.prod.yml logs -f api | grep -i "search\|error"

# Database slow query log'larını kontrol et
docker exec blogapp-postgres-prod cat /var/log/postgresql/postgresql.log | grep -i slow
```

### 2. Performance Metrics

- **Arama response time:** < 500ms hedef
- **Database query time:** < 200ms hedef
- **Error rate:** < 0.1%

---

## 🛡️ Güvenlik Notları

1. **.env dosyası:** Production'da asla commit etmeyin
2. **Backup:** Düzenli olarak otomatik backup alın
3. **SSL/TLS:** HTTPS kullanıldığından emin olun
4. **Rate Limiting:** API rate limit'lerini kontrol edin
5. **Database credentials:** Güçlü şifreler kullanın

---

## 📝 Deployment Checklist

- [ ] Pre-deployment backup alındı
- [ ] Test ortamında doğrulandı
- [ ] Maintenance window planlandı
- [ ] Kod değişiklikleri deploy edildi
- [ ] Database migration uygulandı
- [ ] Migration sonrası kontroller yapıldı
- [ ] Uygulama başlatıldı ve çalışıyor
- [ ] Health check'ler başarılı
- [ ] Arama fonksiyonu test edildi
- [ ] Performans metrikleri kontrol edildi
- [ ] Rollback planı hazır

---

## 🆘 Sorun Giderme

### Migration Hatası

```bash
# Hata log'larını kontrol et
docker logs blogapp-postgres-prod

# Connection problemi
docker exec blogapp-postgres-prod pg_isready -U blogapp_user
```

### Performance Sorunları

```bash
# Index kullanımını kontrol et
docker exec -i blogapp-postgres-prod psql -U blogapp_user -d blogdb -c "SELECT * FROM pg_stat_user_indexes WHERE schemaname = 'public';"

# Slow query'leri bul
docker exec -i blogapp-postgres-prod psql -U blogapp_user -d blogdb -c "SELECT query, mean_exec_time FROM pg_stat_statements ORDER BY mean_exec_time DESC LIMIT 10;"
```

---

## 📞 Destek

Sorun yaşarsanız:
1. Log'ları kontrol edin
2. Backup'tan geri yükleyin
3. Rollback planını uygulayın
4. Development ortamında test edin

---

**Son Güncelleme:** 2024-12-31
**Versiyon:** 1.0

