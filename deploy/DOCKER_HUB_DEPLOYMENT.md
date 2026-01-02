# 🐳 Docker Hub Deployment Rehberi
## Search Optimizasyonu Production Deployment

Bu rehber, arama optimizasyonu değişikliklerini Docker Hub üzerinden production'a deploy etmeniz için hazırlanmıştır.

---

## 📋 Genel Bakış

### Deployment Akışı

```
┌─────────────────────────────────────────────────────────────────┐
│                     LOKAL MAKİNE                                │
│  1. Git pull (son değişiklikler)                                │
│  2. Docker build (API + Frontend)                               │
│  3. Docker push → Docker Hub                                    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                     DOCKER HUB                                  │
│  mrbeko/blog-app:api-latest                                     │
│  mrbeko/blog-app:web-latest                                     │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                     PRODUCTION SUNUCU                           │
│  1. Database backup                                             │
│  2. Docker pull (yeni image'lar)                                │
│  3. Database migration (SearchOptimization.sql)                 │
│  4. Docker restart (API + Frontend)                             │
│  5. Verification                                                │
└─────────────────────────────────────────────────────────────────┘
```

---

## 🖥️ ADIM 1: Lokal Makinede Hazırlık (Windows)

### 1.1 Son Değişiklikleri Çekin

```powershell
# Proje dizinine gidin
cd D:\MrBekoXBlogApp

# Son değişiklikleri çekin (eğer git kullanıyorsanız)
git pull origin main

# VEYA değişiklikleri commit edin
git add .
git commit -m "Search optimization: Turkish char support, relevance scoring, debounce"
git push origin main
```

### 1.2 Docker Image'larını Build Edin

```powershell
# API Image Build
cd D:\MrBekoXBlogApp\src\BlogApp.Server
docker build -t mrbeko/blog-app:api-latest -t mrbeko/blog-app:api-$(Get-Date -Format "yyyyMMdd") .

# Frontend Image Build
cd D:\MrBekoXBlogApp\src\blogapp-web
docker build -t mrbeko/blog-app:web-latest -t mrbeko/blog-app:web-$(Get-Date -Format "yyyyMMdd") --build-arg NEXT_PUBLIC_API_URL=https://mrbekox.dev/api .
```

### 1.3 Docker Hub'a Giriş Yapın

```powershell
# Docker Hub login
docker login

# Username ve password girin
```

### 1.4 Image'ları Push Edin

```powershell
# API image push
docker push mrbeko/blog-app:api-latest
docker push mrbeko/blog-app:api-$(Get-Date -Format "yyyyMMdd")

# Frontend image push
docker push mrbeko/blog-app:web-latest
docker push mrbeko/blog-app:web-$(Get-Date -Format "yyyyMMdd")
```

### 1.5 Migration Dosyasını Hazırlayın

Migration SQL dosyasını sunucuya göndermeniz gerekiyor. Bunu birkaç yolla yapabilirsiniz:

**Yöntem A: SCP ile kopyalama**
```powershell
# SQL dosyasını sunucuya kopyala
scp D:\MrBekoXBlogApp\src\BlogApp.Server\BlogApp.Server.Infrastructure\Persistence\Migrations\SearchOptimization.sql user@your-server:/tmp/
```

**Yöntem B: Git ile (önerilen)**
```powershell
# Değişiklikleri commit edip sunucuda git pull yapın
git add .
git commit -m "Add search optimization migration"
git push origin main
```

---

## 🖥️ ADIM 2: Lokal Build Script (Otomatik)

Tüm işlemleri otomatikleştirmek için bu script'i kullanabilirsiniz:

```powershell
# deploy-to-hub.ps1 dosyasını oluşturun
```

Bu script zaten oluşturuldu: `deploy/deploy-to-hub.ps1`

Kullanım:
```powershell
cd D:\MrBekoXBlogApp\deploy
.\deploy-to-hub.ps1
```

---

## 🌐 ADIM 3: Sunucuda Deployment (Linux)

### 3.1 Sunucuya Bağlanın

```bash
ssh user@your-server-ip
# VEYA
ssh user@mrbekox.dev
```

### 3.2 Backup Alın (KRİTİK!)

```bash
# Proje dizinine gidin
cd /path/to/blogapp/deploy

# PostgreSQL backup
docker exec blogapp-postgres-prod pg_dump -U blogapp_user -d blogdb > backup_$(date +%Y%m%d_%H%M%S).sql

# Backup'ı güvenli bir yere kopyalayın
cp backup_*.sql /path/to/safe/backup/location/
```

### 3.3 Yeni Image'ları Çekin

```bash
# Docker Hub'dan yeni image'ları çek
docker pull mrbeko/blog-app:api-latest
docker pull mrbeko/blog-app:web-latest

# Image'ları kontrol et
docker images | grep mrbeko
```

### 3.4 Database Migration Uygulayın

**Yöntem A: Git ile (önerilen)**
```bash
cd /path/to/blogapp
git pull origin main

# Migration script'ini çalıştır
cd deploy
chmod +x run-production-migration.sh
./run-production-migration.sh ../src/BlogApp.Server/BlogApp.Server.Infrastructure/Persistence/Migrations/SearchOptimization.sql
```

**Yöntem B: Manuel**
```bash
# SQL dosyasını container'a kopyala
docker cp /tmp/SearchOptimization.sql blogapp-postgres-prod:/tmp/

# Migration'ı çalıştır
docker exec -i blogapp-postgres-prod psql -U blogapp_user -d blogdb -f /tmp/SearchOptimization.sql
```

### 3.5 Container'ları Yeniden Başlatın

```bash
cd /path/to/blogapp/deploy

# Sadece API ve Frontend'i yeniden başlat (Database'e dokunma)
docker-compose -f docker-compose.prod.yml up -d --no-deps api frontend

# VEYA tüm container'ları yeniden başlat
docker-compose -f docker-compose.prod.yml down
docker-compose -f docker-compose.prod.yml up -d
```

### 3.6 Doğrulama

```bash
# Container'ların çalıştığını kontrol et
docker-compose -f docker-compose.prod.yml ps

# API log'larını kontrol et
docker-compose -f docker-compose.prod.yml logs -f api --tail=100

# Health check
curl -s https://mrbekox.dev/api/v1/posts?pageSize=1 | head -c 200

# Migration'ı doğrula
docker exec -i blogapp-postgres-prod psql -U blogapp_user -d blogdb -c "SELECT column_name FROM information_schema.columns WHERE table_name = 'posts' AND column_name = 'search_vector';"
```

---

## 📜 ADIM 4: Otomatik Deployment Script'leri

### 4.1 Lokal Build & Push Script (Windows)

`deploy/deploy-to-hub.ps1` dosyası zaten oluşturuldu.

### 4.2 Sunucu Deployment Script (Linux)

`deploy/server-deploy.sh` dosyası zaten oluşturuldu.

---

## ✅ Deployment Checklist

### Lokal Makinede (Windows)
- [ ] Git pull ile son değişiklikler alındı
- [ ] API Docker image build edildi
- [ ] Frontend Docker image build edildi
- [ ] Docker Hub'a login olundu
- [ ] Image'lar Docker Hub'a push edildi

### Sunucuda (Linux)
- [ ] Database backup alındı
- [ ] Yeni image'lar pull edildi
- [ ] Database migration uygulandı
- [ ] Container'lar yeniden başlatıldı
- [ ] Health check başarılı
- [ ] Arama fonksiyonu test edildi

---

## 🔧 Sorun Giderme

### Image Pull Hatası
```bash
# Docker Hub'a yeniden login
docker login

# Image'ı tekrar çek
docker pull mrbeko/blog-app:api-latest
```

### Container Başlamıyor
```bash
# Log'lara bak
docker-compose -f docker-compose.prod.yml logs api

# Container'ı manuel başlat
docker-compose -f docker-compose.prod.yml up api
```

### Migration Hatası
```bash
# Hata mesajını kontrol et
docker exec -i blogapp-postgres-prod psql -U blogapp_user -d blogdb -c "\d posts"

# Rollback
./rollback-migration.sh
```

### Eski Image'a Geri Dönme
```bash
# Önceki tarihli image'ı kullan
docker pull mrbeko/blog-app:api-20241231
docker tag mrbeko/blog-app:api-20241231 mrbeko/blog-app:api-latest

# Container'ı yeniden başlat
docker-compose -f docker-compose.prod.yml up -d --no-deps api
```

---

## 📊 Monitoring

### Log İzleme
```bash
# Tüm container log'ları
docker-compose -f docker-compose.prod.yml logs -f

# Sadece API
docker-compose -f docker-compose.prod.yml logs -f api

# Sadece hatalar
docker-compose -f docker-compose.prod.yml logs api 2>&1 | grep -i error
```

### Performans Kontrolü
```bash
# Arama response time
time curl -s "https://mrbekox.dev/api/v1/posts?search=test&pageSize=20" > /dev/null

# Container resource kullanımı
docker stats --no-stream
```

---

## 🔄 Rollback

Eğer bir sorun olursa:

### 1. Eski Image'a Dön
```bash
# Önceki versiyonu çek (tarih tag'i ile)
docker pull mrbeko/blog-app:api-20241230
docker tag mrbeko/blog-app:api-20241230 mrbeko/blog-app:api-latest

# Restart
docker-compose -f docker-compose.prod.yml up -d --no-deps api frontend
```

### 2. Database Rollback
```bash
# Backup'tan geri yükle
docker exec -i blogapp-postgres-prod psql -U blogapp_user -d blogdb < backup_20241231_120000.sql

# VEYA migration'ı geri al
./rollback-migration.sh
```

---

## 📅 Önerilen Deployment Zamanlaması

1. **En iyi zaman:** Düşük trafik saatleri (gece 02:00-06:00)
2. **Hazırlık:** Deployment'tan 1 saat önce backup
3. **Süre:** Toplam ~15-30 dakika
4. **Downtime:** <1 dakika (sadece container restart süresi)

---

## 🛡️ Güvenlik Notları

1. **Docker Hub credentials:** Asla commit etmeyin
2. **SSH keys:** Güvenli saklayın
3. **Database backup:** Düzenli ve otomatik alın
4. **Image versioning:** Her deploy'da tarih tag'i kullanın
5. **Rollback plan:** Her zaman hazır olsun

---

**Son Güncelleme:** 2024-12-31
**Versiyon:** 1.0

