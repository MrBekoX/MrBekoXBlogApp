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
MIGRATIONS_DIR="../src/BlogApp.Server/BlogApp.Server.Infrastructure/Persistence/Migrations"
# Migration dosyalari (sirayla calistirilir)
MIGRATION_FILES=(
    "SearchOptimization.sql"
    "PartialUniqueIndexes.sql"
)

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
    log_info "Step 3: Database migrations uygulanıyor..."
    
    MIGRATION_SUCCESS=true
    for migration in "${MIGRATION_FILES[@]}"; do
        MIGRATION_PATH="${MIGRATIONS_DIR}/${migration}"
        
        if [ -f "$MIGRATION_PATH" ]; then
            log_info "Migration uygulanıyor: $migration"
            
            # Migration dosyasini container'a kopyala
            docker cp "$MIGRATION_PATH" "${POSTGRES_CONTAINER}:/tmp/migration.sql"
            
            # Migration'i calistir
            if docker exec -i "$POSTGRES_CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -f /tmp/migration.sql 2>/dev/null; then
                log_success "Migration basarili: $migration"
                docker exec "$POSTGRES_CONTAINER" rm /tmp/migration.sql
            else
                log_warn "Migration zaten uygulanmis veya hata: $migration"
                docker exec "$POSTGRES_CONTAINER" rm -f /tmp/migration.sql
            fi
        else
            log_warn "Migration dosyasi bulunamadi: $migration"
        fi
    done
else
    log_info "Step 3: Migration atlanıyor (--with-migration kullanilmadi)"
fi

# Step 4: Container'lari yeniden baslat
echo ""
log_info "Step 4: Container'lar yeniden baslatiliyor..."
docker compose -f "$COMPOSE_FILE" up -d --force-recreate
log_success "Container'lar baslatildi"

# Step 5: API container başlarken EF Core migration otomatik uygulanır (Program.cs MigrateAsync)
echo ""
log_info "Step 5: EF Core migrations API başlatılırken otomatik uygulanacak..."

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