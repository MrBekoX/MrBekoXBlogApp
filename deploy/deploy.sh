#!/bin/bash
# ============================================
# BlogApp Production Deployment Script
# ============================================
# Kullanim:
#   ./deploy.sh                    # Normal deployment
#   ./deploy.sh --with-migration   # Database migration ile deployment
#   ./deploy.sh --help             # Yardim
# ============================================

set -e

# Renkler
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

# Fonksiyonlar
log_info() { echo -e "${CYAN}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Ayarlar
COMPOSE_FILE="docker-compose.prod.yml"
POSTGRES_CONTAINER="blogapp-postgres-prod"
BACKUP_DIR="./backups"
MIGRATION_FILE="../src/BlogApp.Server/BlogApp.Server.Infrastructure/Persistence/Migrations/SearchOptimization.sql"

# Parametreleri isle
WITH_MIGRATION=false
for arg in "$@"; do
    case $arg in
        --with-migration)
            WITH_MIGRATION=true
            shift
            ;;
        --help)
            echo "Kullanim: ./deploy.sh [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --with-migration   Database migration'i da uygula (SearchOptimization.sql)"
            echo "  --help             Bu yardim mesajini goster"
            echo ""
            echo "Ornekler:"
            echo "  ./deploy.sh                    # Normal deployment"
            echo "  ./deploy.sh --with-migration   # Migration ile deployment"
            exit 0
            ;;
    esac
done

echo -e "${CYAN}============================================${NC}"
echo -e "${CYAN}🚀 BlogApp Production Deployment${NC}"
echo -e "${CYAN}============================================${NC}"
echo ""

# .env dosyasini yukle
if [ -f .env ]; then
    source .env
    log_success ".env yuklendi"
else
    log_warn ".env dosyasi bulunamadi, varsayilan degerler kullanilacak"
fi

# Degiskenler
DB_USER="${POSTGRES_USER:-blogapp_user}"
DB_NAME="${POSTGRES_DB:-blogdb}"

# Step 1: Backup
log_info "Step 1: Database backup aliniyor..."
mkdir -p "$BACKUP_DIR"
BACKUP_FILE="${BACKUP_DIR}/backup_$(date +%Y%m%d_%H%M%S).sql"

if docker exec "$POSTGRES_CONTAINER" pg_dump -U "$DB_USER" -d "$DB_NAME" > "$BACKUP_FILE" 2>/dev/null; then
    log_success "Backup olusturuldu: $BACKUP_FILE"
else
    log_warn "Backup alinamadi (database henuz calisiyor olabilir)"
fi

# Step 2: Pull images
echo ""
log_info "Step 2: Yeni image'lar cekiliyor..."
docker compose -f "$COMPOSE_FILE" pull
log_success "Image'lar guncellendi"

# Step 3: Migration (eger istendi ise)
echo ""
if [ "$WITH_MIGRATION" = true ]; then
    log_info "Step 3: Database migration uygulanıyor..."
    
    if [ -f "$MIGRATION_FILE" ]; then
        # Migration dosyasini container'a kopyala
        docker cp "$MIGRATION_FILE" "${POSTGRES_CONTAINER}:/tmp/migration.sql"
        
        # Migration'i calistir
        if docker exec -i "$POSTGRES_CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -f /tmp/migration.sql; then
            log_success "Migration basarili"
            docker exec "$POSTGRES_CONTAINER" rm /tmp/migration.sql
        else
            log_error "Migration basarisiz!"
            log_warn "Backup dosyasi: $BACKUP_FILE"
            exit 1
        fi
    else
        log_warn "Migration dosyasi bulunamadi: $MIGRATION_FILE"
    fi
else
    log_info "Step 3: Migration atlanıyor (--with-migration kullanilmadi)"
fi

# Step 4: Container'lari yeniden baslat
echo ""
log_info "Step 4: Container'lar yeniden baslatiliyor..."
docker compose -f "$COMPOSE_FILE" up -d
log_success "Container'lar baslatildi"

# Step 5: EF Core migration (API icinde)
echo ""
log_info "Step 5: EF Core migrations kontrol ediliyor..."
docker compose -f "$COMPOSE_FILE" exec -T api dotnet ef database update 2>/dev/null || log_warn "EF migration atlandi veya hata"

# Step 6: Health check
echo ""
log_info "Step 6: Health check yapiliyor..."
sleep 5

if docker compose -f "$COMPOSE_FILE" ps | grep -q "Up"; then
    log_success "Tum container'lar calisiyor"
else
    log_error "Bazi container'lar calismıyor!"
    docker compose -f "$COMPOSE_FILE" ps
fi

# Step 7: Migration dogrulama (eger uygulandi ise)
if [ "$WITH_MIGRATION" = true ]; then
    echo ""
    log_info "Step 7: Migration dogrulaniyor..."
    
    if docker exec -i "$POSTGRES_CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -c "SELECT column_name FROM information_schema.columns WHERE table_name = 'posts' AND column_name = 'search_vector';" 2>/dev/null | grep -q "search_vector"; then
        log_success "search_vector kolonu mevcut"
    else
        log_warn "search_vector kolonu bulunamadi"
    fi
fi

# Ozet
echo ""
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}✅ Deployment tamamlandi!${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""
docker compose -f "$COMPOSE_FILE" ps
echo ""
log_info "Backup: $BACKUP_FILE"
echo ""