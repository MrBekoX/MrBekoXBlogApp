# BlogApp Deployment Guide

Bu klasör production ortamı için deployment dosyalarını içerir.

## 📋 Gereksinimler

- Docker (20.10+)
- Docker Compose (2.0+)
- En az 2GB RAM
- En az 10GB disk alanı

## 🚀 Hızlı Başlangıç

### 1. Environment Dosyasını Hazırlayın

```bash
cd deploy
cp .env.example .env
```

`.env` dosyasını düzenleyin ve aşağıdaki değerleri değiştirin:

- `POSTGRES_PASSWORD`: Güçlü bir şifre
- `JWT_SECRET`: En az 32 karakterlik güçlü bir secret key
- `FRONTEND_URL`: Production frontend URL'i (örn: `https://yourdomain.com`)
- `API_URL`: Production API URL'i (örn: `https://api.yourdomain.com` veya `https://yourdomain.com/api`)

### 2. SSL Sertifikaları (Opsiyonel ama Önerilir)

HTTPS kullanmak için SSL sertifikalarınızı `deploy/ssl/` klasörüne koyun:

```bash
mkdir -p ssl
# Let's Encrypt kullanıyorsanız:
cp /etc/letsencrypt/live/yourdomain.com/fullchain.pem ssl/cert.pem
cp /etc/letsencrypt/live/yourdomain.com/privkey.pem ssl/key.pem
```

Sonra `nginx.conf` dosyasındaki HTTPS server bloğunun yorumlarını kaldırın.

### 3. Deployment

```bash
# Deployment script'ini çalıştırılabilir yapın
chmod +x deploy.sh

# Deploy edin
./deploy.sh
```

Veya manuel olarak:

```bash
docker compose -f docker-compose.prod.yml --env-file .env up -d --build
```

### 4. Database Migration

İlk deployment'tan sonra database migration'ları çalıştırın:

```bash
./deploy.sh migrate
```

Veya manuel olarak:

```bash
docker compose -f docker-compose.prod.yml exec api dotnet ef database update
```

## 📝 Yönetim Komutları

### Servisleri Durdurma

```bash
./deploy.sh stop
# veya
docker compose -f docker-compose.prod.yml down
```

### Servisleri Yeniden Başlatma

```bash
./deploy.sh restart
# veya
docker compose -f docker-compose.prod.yml restart
```

### Logları Görüntüleme

```bash
# Tüm servislerin logları
./deploy.sh logs

# Belirli bir servisin logları
./deploy.sh logs api
./deploy.sh logs frontend
```

### Servis Durumunu Kontrol Etme

```bash
docker compose -f docker-compose.prod.yml ps
```

## 🔧 Yapılandırma

### Port Değiştirme

`.env` dosyasında port değişkenlerini düzenleyin:

```env
HTTP_PORT=80
HTTPS_PORT=443
API_PORT=8080
FRONTEND_PORT=3000
```

### Nginx Yapılandırması

`nginx.conf` dosyasını düzenleyerek:
- Domain adlarını değiştirin
- SSL yapılandırmasını özelleştirin
- Rate limiting ekleyin
- Caching ayarlarını yapın

### Database Backup

```bash
# Backup oluştur
docker compose -f docker-compose.prod.yml exec postgres pg_dump -U blogapp_user blogdb > backup_$(date +%Y%m%d_%H%M%S).sql

# Backup'tan geri yükleme
docker compose -f docker-compose.prod.yml exec -T postgres psql -U blogapp_user blogdb < backup.sql
```

## 🔒 Güvenlik

### Production Checklist

- [ ] `.env` dosyasında güçlü şifreler kullanıldı
- [ ] JWT_SECRET en az 32 karakter
- [ ] SSL sertifikaları yapılandırıldı
- [ ] CORS ayarları production URL'lerine göre güncellendi
- [ ] Firewall kuralları yapılandırıldı
- [ ] Düzenli backup planı oluşturuldu
- [ ] Log rotation yapılandırıldı

### Environment Variables Güvenliği

`.env` dosyası **ASLA** Git'e commit edilmemelidir. `.gitignore` dosyasında zaten ignore edilmiştir.

## 🐛 Sorun Giderme

### Servisler Başlamıyor

```bash
# Logları kontrol edin
docker compose -f docker-compose.prod.yml logs

# Servisleri yeniden başlatın
docker compose -f docker-compose.prod.yml restart
```

### Database Bağlantı Hatası

- PostgreSQL container'ının çalıştığından emin olun
- `.env` dosyasındaki database bilgilerini kontrol edin
- Network bağlantısını kontrol edin: `docker network ls`

### Port Çakışması

Eğer portlar kullanılıyorsa, `.env` dosyasında farklı portlar belirleyin veya çakışan servisleri durdurun.

## 📚 Ek Kaynaklar

- [Docker Documentation](https://docs.docker.com/)
- [Docker Compose Documentation](https://docs.docker.com/compose/)
- [Nginx Documentation](https://nginx.org/en/docs/)
- [PostgreSQL Documentation](https://www.postgresql.org/docs/)

