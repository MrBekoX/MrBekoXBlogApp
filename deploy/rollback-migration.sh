#!/bin/bash
# Rollback Script for Search Optimization Migration
# Use this if you need to revert the migration

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}========================================${NC}"
echo -e "${YELLOW}Rollback: Search Optimization Migration${NC}"
echo -e "${YELLOW}========================================${NC}"
echo ""

CONTAINER_NAME="${POSTGRES_CONTAINER:-blogapp-postgres-prod}"
DB_NAME="${POSTGRES_DB:-blogdb}"
DB_USER="${POSTGRES_USER:-blogapp_user}"

# Confirmation
echo -e "${RED}⚠️  WARNING: This will remove all search optimization features!${NC}"
read -p "Are you sure you want to proceed? (yes/no): " confirm
if [ "$confirm" != "yes" ]; then
    echo "Rollback cancelled."
    exit 0
fi

echo ""
echo -e "${YELLOW}Starting rollback...${NC}"

# Rollback SQL
docker exec -i "${CONTAINER_NAME}" psql -U "${DB_USER}" -d "${DB_NAME}" << EOF
-- Drop trigger
DROP TRIGGER IF EXISTS posts_search_vector_trigger ON posts;

-- Drop function
DROP FUNCTION IF EXISTS posts_search_vector_update();

-- Drop indexes
DROP INDEX IF EXISTS IX_posts_search_vector;
DROP INDEX IF EXISTS IX_posts_title_trgm;
DROP INDEX IF EXISTS IX_posts_content_trgm;
DROP INDEX IF EXISTS IX_posts_excerpt_trgm;
DROP INDEX IF EXISTS IX_posts_slug_trgm;
DROP INDEX IF EXISTS IX_posts_status_publishedat;
DROP INDEX IF EXISTS IX_posts_status_isfeatured_publishedat;
DROP INDEX IF EXISTS IX_posts_isdeleted_status;
DROP INDEX IF EXISTS IX_posts_categoryid_status;

-- Drop column
ALTER TABLE posts DROP COLUMN IF EXISTS search_vector;

-- Note: pg_trgm extension is kept as it might be used by other features
-- To remove it: DROP EXTENSION IF EXISTS pg_trgm;
EOF

if [ $? -eq 0 ]; then
    echo ""
    echo -e "${GREEN}✅ Rollback completed successfully!${NC}"
else
    echo ""
    echo -e "${RED}❌ Rollback failed!${NC}"
    exit 1
fi

