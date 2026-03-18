# Upload 404 Hatası Analiz Raporu

## Hata Özeti

```
GET http://localhost:8080/uploads/images/Ekran%20g%C3%B6r%C3%BCnt%C3%BCs%C3%BC%202025-12-28%20180550_d8f2a87b.webp 404 (Not Found)
```

## 🔍 Root Cause (Temel Neden)

**Docker Development Ortamında Volume Mount Uyumsuzluğu**

### Sorunun Teknik Analizi

#### 1. Mevcut Yapı

**`docker/docker-compose.yml` (Development)**:
```yaml
backend:
  volumes:
    - uploads_data:/app/uploads  # ❌ Named Volume
```

**`src/BlogApp.Server/BlogApp.Server.Api/Program.cs`**:
```csharp
var uploadsPath = Path.Combine(app.Environment.ContentRootPath, "uploads");
// Container'da: /app/uploads

app.UseStaticFiles(new StaticFileOptions
{
    FileProvider = new PhysicalFileProvider(uploadsPath),
    RequestPath = "/uploads"
});
```

**`FileStorageService.cs`**:
```csharp
var imagesFolder = Path.Combine(_uploadsFolder, "images");
// Container'da: /app/uploads/images
return $"/uploads/images/{uniqueFileName}";
```

#### 2. Sorun Akışı

```
┌─────────────────────────────────────────────────────────────────┐
│                        HOST (Bilgisayar)                         │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  Yerel Uploads Klasörü                                  │    │
│  │  src/BlogApp.Server/BlogApp.Server.Api/uploads/images/  │    │
│  │  └── Ekran görüntüsü 2025-12-28 180550_d8f2a87b.webp   │    │
│  └─────────────────────────────────────────────────────────┘    │
│                              │                                   │
│                              │  ❌ Senkronizasyon YOK!           │
│                              ▼                                   │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  Docker Named Volume: uploads_data                      │    │
│  │  (İçerik host ile paylaşılmıyor)                        │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                     CONTAINER (Backend)                          │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  Container Uploads Klasörü                              │    │
│  │  /app/uploads/images/                                   │    │
│  │  └── (BOŞ - dosya burada değil!)                        │    │
│  └─────────────────────────────────────────────────────────┘    │
│                              │                                   │
│                              ▼                                   │
│                    404 Not Found Response                        │
└─────────────────────────────────────────────────────────────────┘
```

#### 3. Neden Kaynaklanıyor?

| Durum | Açıklama |
|-------|----------|
| **Upload Sırasında** | Dosya `FileStorageService` tarafından `/app/uploads/images/` altına kaydedilir |
| **Named Volume** | `uploads_data:/app/uploads` kullanıldığı için dosya Docker volume'una yazılır |
| **Host Erişimi** | Host üzerindeki `src/.../uploads/` klasörü container'dan bağımsızdır |
| **Request** | Browser `http://localhost:8080/uploads/images/...` isteği atar |
| **404 Hatası** | Container içinde `/app/uploads/images/` boş olduğu için dosya bulunamaz |

## 🎯 Etkilenen Senaryolar

### Senaryo 1: Docker Development (❌ Hatalı)
```bash
cd docker && docker-compose up -d
# Upload yapılır → Dosya container volume'una kaydedilir
# GET /uploads/images/... → 404
```

### Senaryo 2: Yerel Geliştirme (✅ Çalışır)
```bash
cd src/BlogApp.Server/BlogApp.Server.Api
dotnet run
# Upload yapılır → Dosya yerel uploads/ klasörüne kaydedilir
# GET /uploads/images/... → 200 OK
```

### Senaryo 3: Production (✅ Çalışır)
```yaml
# deploy/docker-compose.prod.yml
deploy:
  volumes:
    - ./uploads:/app/uploads  # ✅ Bind mount - host klasörü eşlenir
```

## ✅ Çözüm Önerileri

### Öneri 1: Bind Mount Kullanımı (Önerilen) ✅

**`docker/docker-compose.yml` değişikliği**:
```yaml
backend:
  volumes:
    # ❌ Kaldır: uploads_data:/app/uploads
    # ✅ Ekle: Host uploads klasörünü container'a bağla
    - ../src/BlogApp.Server/BlogApp.Server.Api/uploads:/app/uploads
```

**Avantajları**:
- Host ve container dosyaları senkronize
- Development'ta değişiklikler anında görülür
- Yerel test kolaylığı

**Dezavantajları**:
- Container silinse bile dosyalar host'ta kalır
- Cross-platform path sorunları olabilir

---

### Öneri 2: Named Volume + Volume Inspect (Alternatif)

Named volume kullanmaya devam edip, dosyaları incelemek için:
```bash
# Container'a gir
docker exec -it blogapp-backend /bin/bash

# Uploads klasörünü kontrol et
ls -la /app/uploads/images/

# Veya volume'u host'a kopyala
docker cp blogapp-backend:/app/uploads ./uploads_backup
```

---

### Öneri 3: Docker Volume Yönetimi (Gelişmiş)

```bash
# Volume içeriğini kontrol et
docker volume inspect uploads_data

# Volume'u mount ederek incele
docker run --rm -v uploads_data:/data -it alpine sh
```

---

## 🔧 Hızlı Düzeltme

### Adım 1: docker-compose.yml Güncelleme

```yaml
# docker/docker-compose.yml
services:
  backend:
    volumes:
      # uploads_data:/app/uploads  # KALDIR
      - ../src/BlogApp.Server/BlogApp.Server.Api/uploads:/app/uploads  # EKLE
```

### Adım 2: Container'ı Yeniden Başlat

```bash
cd docker
docker-compose down
docker-compose up -d
```

### Adım 3: Doğrulama

```bash
# Container içinde uploads klasörünü kontrol et
docker exec blogapp-backend ls -la /app/uploads/images/

# Dosyaya erişim testi
curl -I http://localhost:8080/uploads/images/Ekran%20g%C3%B6r%C3%BCnt%C3%BCs%C3%BC%202025-12-28%20180550_d8f2a87b.webp
```

## 📊 Karşılaştırma Tablosu

| Ortam | Volume Tipi | Senkronizasyon | Durum |
|-------|-------------|----------------|-------|
| Development (Mevcut) | Named Volume (`uploads_data`) | ❌ Yok | **404 Hatası** |
| Development (Düzeltilmiş) | Bind Mount | ✅ Var | Çalışır |
| Production | Bind Mount (`./uploads`) | ✅ Var | Çalışır |
| Yerel (dotnet run) | Doğrudan erişim | ✅ Var | Çalışır |

## 📝 Önemli Notlar

1. **Production farklı çalışıyor**: `deploy/docker-compose.prod.yml` zaten bind mount kullanıyor (`./uploads:/app/uploads`)

2. **Nginx yapılandırması**: Nginx'de uploads için özel bir location tanımlı değil, API üzerinden servis ediliyor

3. **Dosya izinleri**: Bind mount kullanıldığında container ve host kullanıcı ID'leri uyumlu olmalı

4. **Cross-platform**: Windows/WSL ortamında path formatlarına dikkat edilmeli

## 🔗 İlgili Dosyalar

- `docker/docker-compose.yml` - Development compose dosyası
- `deploy/docker-compose.prod.yml` - Production compose dosyası
- `src/BlogApp.Server/BlogApp.Server.Api/Program.cs` - Static files yapılandırması
- `src/BlogApp.Server/BlogApp.Server.Infrastructure/Services/FileStorageService.cs` - Dosya kaydetme servisi
- `src/BlogApp.Server/BlogApp.Server.Api/Endpoints/MediaEndpoints.cs` - Upload endpoint'leri

---

**Rapor Tarihi**: 2026-02-04  
**Ortam**: Docker Development (localhost:8080)
