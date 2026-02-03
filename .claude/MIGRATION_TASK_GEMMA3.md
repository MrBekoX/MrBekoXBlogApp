Tamam, dosyaları düzgünce inceledim. İşte **gerçek** implementasyon planı:

---

# Ollama Gemma3:8b Migration - Implementation Plan

## 📁 Dosya Analizi

### Değişecek Dosyalar:
1. ✅ `app/core/config.py` - ZhipuAI → Ollama config
2. ✅ `app/agent/simple_blog_agent.py` - LLM provider değişikliği
3. ✅ `requirements.txt` - Dependency update
4. ✅ `.env` - Environment variables
5. ✅ `docker-compose.yml` - Ollama service ekleme

### Değişmeyen Dosyalar:
- ❌ `app/api/routes.py` - Hiç dokunma
- ❌ `app/api/endpoints.py` - Hiç dokunma
- ❌ `app/messaging/consumer.py` - Hiç dokunma
- ❌ `app/messaging/processor.py` - Hiç dokunma
- ❌ `app/core/cache.py` - Hiç dokunma

---

## 🔧 Implementation Steps

### Step 1: `requirements.txt` Update

**Eski:**
```txt
langchain-community
# veya langchain içinde ChatZhipuAI varsa
```

**Yeni:**
```txt
langchain-ollama>=0.1.0
langchain-core>=0.3.0
```

**Claude Code Komutu:**
```bash
claude-code "Update requirements.txt: 
Remove any ZhipuAI or ChatZhipuAI related packages.
Add: langchain-ollama>=0.1.0
Keep all other packages exactly as they are (fastapi, pydantic, redis, aio-pika, httpx, slowapi, uvicorn, pydantic-settings)"
```

---

### Step 2: `app/core/config.py` Refactor

**SİLİNECEKLER (satır satır):**
```python
# Line ~18-22: ZhipuAI Configuration
zhipuai_api_key: str = Field(...)
zhipuai_api_key_backup: Optional[str] = Field(...)
llm_model: str = "glm-4"

# Line ~23-28: validate_api_key
@validator('zhipuai_api_key')
def validate_api_key(cls, v):
    if not v or len(v) < 32:
        raise ValueError('API key must be at least 32 characters long')
    return v

# Line ~29-34: validate_backup_api_key
@validator('zhipuai_api_key_backup')
def validate_backup_api_key(cls, v):
    if v is not None and len(v) < 32:
        raise ValueError('Backup API key must be at least 32 characters long')
    return v

# Line ~70-84: get_current_api_key & rotate_api_key methods
def get_current_api_key(self) -> str:
    ...
    
def rotate_api_key(self) -> bool:
    ...
```

**EKLENECEKLEbilecek (ZhipuAI config yerine):**
```python
# Ollama Configuration
ollama_base_url: str = Field(
    default="http://localhost:11434",
    description="Ollama API base URL"
)
ollama_model: str = Field(
    default="gemma3:8b",
    description="Ollama model name"
)
ollama_timeout: int = Field(
    default=120,
    description="Ollama request timeout in seconds"
)
ollama_num_ctx: int = Field(
    default=128000,
    description="Ollama context window size (Gemma3 supports 128K)"
)
ollama_temperature: float = Field(
    default=0.7,
    ge=0.0,
    le=2.0,
    description="LLM temperature"
)
```

**KALACAKLAR (değişmeyecek):**
```python
# Redis Configuration
redis_url: str = "redis://localhost:6379/0"

# RabbitMQ Configuration  
rabbitmq_host: str = Field(...)
rabbitmq_port: int = 5672
rabbitmq_user: str = Field(...)
rabbitmq_pass: str = Field(...)
rabbitmq_vhost: str = "/"

@validator('rabbitmq_user')
def validate_rabbitmq_user(cls, v):
    ...

# Backend API Configuration
backend_api_url: str = "http://localhost:5116/api/v1"

# Server Settings
host: str = "0.0.0.0"
port: int = 8000
debug: bool = False

@property
def rabbitmq_url(self) -> str:
    ...
```

**Claude Code Komutu:**
```bash
claude-code "Refactor app/core/config.py:

DELETE these fields and methods:
- zhipuai_api_key (line ~18)
- zhipuai_api_key_backup (line ~21)
- llm_model (line ~25)
- @validator('zhipuai_api_key') method (line ~27-31)
- @validator('zhipuai_api_key_backup') method (line ~33-37)
- get_current_api_key() method (line ~72-80)
- rotate_api_key() method (line ~82-91)

ADD these new fields after model_config:
ollama_base_url: str = Field(default='http://localhost:11434', description='Ollama API base URL')
ollama_model: str = Field(default='gemma3:8b', description='Ollama model name')
ollama_timeout: int = Field(default=120, description='Ollama request timeout in seconds')
ollama_num_ctx: int = Field(default=128000, description='Context window size')
ollama_temperature: float = Field(default=0.7, ge=0.0, le=2.0, description='LLM temperature')

KEEP UNCHANGED:
- All Redis config
- All RabbitMQ config and validators
- backend_api_url
- host, port, debug
- rabbitmq_url property
- get_settings() function"
```

---

### Step 3: `app/agent/simple_blog_agent.py` Refactor

**DEĞİŞECEK SATIRLAR:**

**Line 6-7 (Import):**
```python
# ESKİ:
from langchain_community.chat_models import ChatZhipuAI

# YENİ:
from langchain_ollama import ChatOllama
```

**Line 16 (Docstring):**
```python
# ESKİ:
"""
RAG'siz blog analiz agent'i.

Blog makaleleri için doğrudan LLM çağrıları ile:
...
"""

# YENİ:
"""
RAG'siz blog analiz agent'i - Ollama Gemma3 ile.

Blog makaleleri için doğrudan LLM çağrıları ile:
...
"""
```

**Line 30 (Type annotation):**
```python
# ESKİ:
self._llm: Optional[ChatZhipuAI] = None

# YENİ:
self._llm: Optional[ChatOllama] = None
```

**Line 33-48 (initialize method):**
```python
# ESKİ:
def initialize(self) -> None:
    """Initialize the agent with LLM."""
    if self._initialized:
        return

    logger.info("Initializing SimpleBlogAgent...")

    # Initialize LLM with ZhipuAI
    self._llm = ChatZhipuAI(
        model=settings.llm_model,
        api_key=settings.zhipuai_api_key,
        temperature=0.7,
        request_timeout=60,
        max_retries=3,
        retry_delay=1,
    )

    self._initialized = True
    logger.info("SimpleBlogAgent initialized successfully")

# YENİ:
def initialize(self) -> None:
    """Initialize the agent with Ollama Gemma3."""
    if self._initialized:
        return

    logger.info("Initializing SimpleBlogAgent with Ollama Gemma3...")

    # Initialize LLM with Ollama
    self._llm = ChatOllama(
        model=settings.ollama_model,
        base_url=settings.ollama_base_url,
        temperature=settings.ollama_temperature,
        timeout=settings.ollama_timeout,
        num_ctx=settings.ollama_num_ctx,
    )

    self._initialized = True
    logger.info("SimpleBlogAgent initialized successfully")
```

**KALACAK HER ŞEY:**
- Tüm method signatures (summarize_article, extract_keywords, vb.)
- Tüm prompt templates
- Tüm async/await logic
- Tüm error handling
- calculate_reading_time (sync method)
- full_analysis method
- Global instance: `simple_blog_agent = SimpleBlogAgent()`

**Claude Code Komutu:**
```bash
claude-code "Refactor app/agent/simple_blog_agent.py:

Line 6: Change import
FROM: from langchain_community.chat_models import ChatZhipuAI
TO: from langchain_ollama import ChatOllama

Line 16: Update docstring first line
FROM: RAG'siz blog analiz agent'i.
TO: RAG'siz blog analiz agent'i - Ollama Gemma3 ile.

Line 30: Change type annotation
FROM: self._llm: Optional[ChatZhipuAI] = None
TO: self._llm: Optional[ChatOllama] = None

Lines 33-48: Replace entire initialize() method with:
def initialize(self) -> None:
    '''Initialize the agent with Ollama Gemma3.'''
    if self._initialized:
        return

    logger.info('Initializing SimpleBlogAgent with Ollama Gemma3...')

    self._llm = ChatOllama(
        model=settings.ollama_model,
        base_url=settings.ollama_base_url,
        temperature=settings.ollama_temperature,
        timeout=settings.ollama_timeout,
        num_ctx=settings.ollama_num_ctx,
    )

    self._initialized = True
    logger.info('SimpleBlogAgent initialized successfully')

KEEP EVERYTHING ELSE UNCHANGED:
- All method implementations (summarize_article through full_analysis)
- All prompts
- All error handling
- Global instance at the end"
```

---

### Step 4: `.env` File Update

**Yeni `.env` şablonu:**
```bash
# Ollama Configuration
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=gemma3:8b
OLLAMA_TIMEOUT=120
OLLAMA_NUM_CTX=128000
OLLAMA_TEMPERATURE=0.7

# Redis
REDIS_URL=redis://localhost:6379/0

# RabbitMQ
RABBITMQ_HOST=localhost
RABBITMQ_PORT=5672
RABBITMQ_USER=admin
RABBITMQ_PASS=your_secure_password
RABBITMQ_VHOST=/

# Backend API
BACKEND_API_URL=http://localhost:5116/api/v1

# Server
HOST=0.0.0.0
PORT=8000
DEBUG=false
```

**Claude Code Komutu:**
```bash
claude-code "Create new .env.example file with Ollama configuration:

# Ollama Configuration
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=gemma3:8b
OLLAMA_TIMEOUT=120
OLLAMA_NUM_CTX=128000
OLLAMA_TEMPERATURE=0.7

# Redis
REDIS_URL=redis://localhost:6379/0

# RabbitMQ
RABBITMQ_HOST=localhost
RABBITMQ_PORT=5672
RABBITMQ_USER=admin
RABBITMQ_PASS=your_secure_password
RABBITMQ_VHOST=/

# Backend API
BACKEND_API_URL=http://localhost:5116/api/v1

# Server
HOST=0.0.0.0
PORT=8000
DEBUG=false"
```

---

### Step 5: `docker-compose.yml` Update

**EKLENECEbilecek Ollama Service:**
```yaml
services:
  ollama:
    image: ollama/ollama:latest
    container_name: ollama
    ports:
      - "11434:11434"
    volumes:
      - ollama_data:/root/.ollama
    healthcheck:
      test: ["CMD", "ollama", "list"]
      interval: 30s
      timeout: 10s
      retries: 5
      start_period: 30s

  ai-agent:
    # Mevcut config
    depends_on:
      ollama:
        condition: service_healthy
      redis:
        condition: service_started
      rabbitmq:
        condition: service_started
    environment:
      - OLLAMA_BASE_URL=http://ollama:11434
      - OLLAMA_MODEL=gemma3:8b
      - OLLAMA_TIMEOUT=120
      - OLLAMA_NUM_CTX=128000
      - OLLAMA_TEMPERATURE=0.7
      - REDIS_URL=redis://redis:6379/0
      - RABBITMQ_HOST=rabbitmq
      - RABBITMQ_USER=${RABBITMQ_USER}
      - RABBITMQ_PASS=${RABBITMQ_PASS}
      - BACKEND_API_URL=${BACKEND_API_URL}

volumes:
  ollama_data:
  # Diğer volume'lar
```

**Claude Code Komutu:**
```bash
claude-code "Update docker-compose.yml:

ADD new service 'ollama' before ai-agent service:
  ollama:
    image: ollama/ollama:latest
    container_name: ollama
    ports:
      - '11434:11434'
    volumes:
      - ollama_data:/root/.ollama
    healthcheck:
      test: ['CMD', 'ollama', 'list']
      interval: 30s
      timeout: 10s
      retries: 5
      start_period: 30s

UPDATE ai-agent service:
- Add ollama to depends_on with condition: service_healthy
- Update environment variables to use Ollama config (OLLAMA_BASE_URL, OLLAMA_MODEL, etc.)
- Remove any ZhipuAI related env vars

ADD to volumes section:
  ollama_data:"
```

---

### Step 6: Ollama Init Script

**Yeni dosya: `scripts/init-ollama.sh`**
```bash
#!/bin/bash
set -e

echo "Waiting for Ollama service..."
until curl -s http://localhost:11434/api/tags > /dev/null 2>&1; do
    echo "Ollama not ready, waiting..."
    sleep 2
done

echo "Ollama is ready!"
echo "Pulling gemma3:8b model..."
ollama pull gemma3:8b

echo "Gemma3:8b model ready!"
ollama list
```

**Claude Code Komutu:**
```bash
claude-code "Create scripts/init-ollama.sh with Ollama initialization script.
Make it executable (chmod +x).
Script should wait for Ollama service and pull gemma3:8b model."
```

---

## ✅ Migration Checklist

### Pre-Migration
- [ ] Create git branch: `feature/ollama-gemma3`
- [ ] Create backup tag: `v2.0.0-zhipuai-final`
- [ ] Backup current `.env` file

### Code Changes
- [ ] Update `requirements.txt`
- [ ] Refactor `app/core/config.py`
- [ ] Refactor `app/agent/simple_blog_agent.py`
- [ ] Create new `.env.example`
- [ ] Update `docker-compose.yml`
- [ ] Create `scripts/init-ollama.sh`

### Local Setup
- [ ] Install Ollama: `https://ollama.com/download`
- [ ] Pull model: `ollama pull gemma3:8b`
- [ ] Update `.env` with new variables
- [ ] Install new dependencies: `pip install -r requirements.txt`

### Verification
- [ ] `ollama list` shows gemma3:8b
- [ ] Docker compose builds without errors
- [ ] Health endpoint responds: `curl http://localhost:8000/health`
- [ ] Simple API test works

---

## 🚀 Execution Order

```bash
# 1. Backup
git checkout -b feature/ollama-gemma3
git tag v2.0.0-zhipuai-final
cp .env .env.backup

# 2. Install Ollama
# Download from https://ollama.com/download
ollama pull gemma3:8b

# 3. Code changes (Claude Code commands yukarıda)

# 4. Install dependencies
pip install -r requirements.txt

# 5. Update .env
cp .env.example .env
# Edit with your values

# 6. Start services
docker-compose build
docker-compose up -d

# 7. Initialize Ollama in container
docker-compose exec ollama ollama pull gemma3:8b

# 8. Verify
curl http://localhost:8000/health
```

