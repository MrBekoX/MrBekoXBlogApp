# ⚡ Hızlı Deployment Rehberi

## 🖥️ Windows (Lokal Makine) - Build & Push

```powershell
# 1. Proje dizinine git
cd D:\MrBekoXBlogApp\deploy

# 2. Otomatik script ile build & push
.\deploy-to-hub.ps1
```

VEYA manuel:

```powershell
# API build & push
cd D:\MrBekoXBlogApp\src\BlogApp.Server
docker build -t mrbeko/blog-app:api-latest .
docker push mrbeko/blog-app:api-latest

# Frontend build & push
cd D:\MrBekoXBlogApp\src\blogapp-web
docker build -t mrbeko/blog-app:web-latest --build-arg NEXT_PUBLIC_API_URL=https://mrbekox.dev/api .
docker push mrbeko/blog-app:web-latest
```

---

## 🌐 Linux (Production Sunucu) - Deploy

```bash
# 1. Sunucuya baglan
ssh user@mrbekox.dev

# 2. Deploy dizinine git
cd /path/to/blogapp/deploy

# 3. Deploy (normal guncelleme)
./deploy.sh

# VEYA migration ile deploy (ilk seferde)
./deploy.sh --with-migration
```

---

## 📋 Komut Referansi

| Komut | Aciklama |
|-------|----------|
| `./deploy.sh` | Normal deployment (image pull + restart) |
| `./deploy.sh --with-migration` | Migration ile deployment (SearchOptimization.sql) |
| `./deploy.sh --help` | Yardim |

---

## 🔄 Rollback

```bash
# Eski image'a don
docker pull mrbeko/blog-app:api-20241230
docker tag mrbeko/blog-app:api-20241230 mrbeko/blog-app:api-latest
docker compose -f docker-compose.prod.yml up -d

# Database rollback (gerekirse)
./rollback-migration.sh
```

---

## ✅ Dogrulama

```bash
# API test
curl https://mrbekox.dev/api/v1/posts?search=test&pageSize=5

# Migration dogrulama
docker exec -i blogapp-postgres-prod psql -U blogapp_user -d blogdb -c "SELECT column_name FROM information_schema.columns WHERE table_name = 'posts' AND column_name = 'search_vector';"
```

