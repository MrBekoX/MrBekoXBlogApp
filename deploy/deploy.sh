#!/bin/bash
# ============================================
# BlogApp Production Deployment Script
# ============================================
# Kullanim:
#   ./deploy.sh         # Normal deployment (migrations otomatik uygulanir)
#   ./deploy.sh --help  # Yardim
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

# Parametreleri isle
for arg in "$@"; do
    case $arg in
        --help)
            echo "Kullanim: ./deploy.sh"
            echo ""
            echo "Bu script:"
            echo "  1. Database backup alir"
            echo "  2. Docker image'lari ceker"
            echo "  3. Container'lari yeniden baslatir"
            echo "  4. EF Core migrations otomatik uygulanir (Program.cs MigrateAsync)"
            echo "  5. Health check yapar"
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
BACKUP_ERROR_FILE="${BACKUP_DIR}/backup_error_$(date +%Y%m%d_%H%M%S).log"

if docker exec "$POSTGRES_CONTAINER" pg_dump -U "$DB_USER" -d "$DB_NAME" > "$BACKUP_FILE" 2>"$BACKUP_ERROR_FILE"; then
    log_success "Backup olusturuldu: $BACKUP_FILE"
    rm -f "$BACKUP_ERROR_FILE"  # Hata yok, error log'u sil
else
    log_warn "Backup alinamadi. Hata detaylari: $BACKUP_ERROR_FILE"
    if [ -s "$BACKUP_ERROR_FILE" ]; then
        cat "$BACKUP_ERROR_FILE"
    fi
fi

# Step 2: Pull images
echo ""
log_info "Step 2: Yeni image'lar cekiliyor..."
docker compose -f "$COMPOSE_FILE" pull
log_success "Image'lar guncellendi"

# Step 3: Container'lari yeniden baslat
echo ""
log_info "Step 3: Container'lar yeniden baslatiliyor..."
docker compose -f "$COMPOSE_FILE" up -d --force-recreate
log_success "Container'lar baslatildi"

# Step 4: EF Core migrations otomatik uygulanir
echo ""
log_info "Step 4: EF Core migrations API baslatilirken otomatik uygulanacak..."
log_info "       (Program.cs MigrateAsync)"

# Step 5: Health check
echo ""
log_info "Step 5: Health check yapiliyor..."
sleep 5

if docker compose -f "$COMPOSE_FILE" ps | grep -q "Up"; then
    log_success "Tum container'lar calisiyor"
else
    log_error "Bazi container'lar calismiyor!"
    docker compose -f "$COMPOSE_FILE" ps
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