// =============================================================================
// GEO Entity Linking — Bilinen teknoloji/konsept isimlerini schema.org Thing
// entity'lerine cevirir. AI arama motorlari entity disambiguation icin
// about.sameAs property'sini kullanir.
// =============================================================================

interface SchemaEntity {
  '@type': 'Thing';
  name: string;
  sameAs?: string | string[];
}

interface EntityInfo {
  wiki: string;
  docs?: string;
}

/**
 * Bilinen teknoloji isimlerinin Wikipedia + resmi dokumantasyon URL mapping'i.
 * Key: lowercase normalize edilmis isim.
 */
const ENTITY_MAP: Record<string, EntityInfo> = {
  // Programming Languages
  'c#': {
    wiki: 'https://en.wikipedia.org/wiki/C_Sharp_(programming_language)',
    docs: 'https://learn.microsoft.com/en-us/dotnet/csharp/',
  },
  'csharp': {
    wiki: 'https://en.wikipedia.org/wiki/C_Sharp_(programming_language)',
    docs: 'https://learn.microsoft.com/en-us/dotnet/csharp/',
  },
  'python': {
    wiki: 'https://en.wikipedia.org/wiki/Python_(programming_language)',
    docs: 'https://docs.python.org/3/',
  },
  'javascript': {
    wiki: 'https://en.wikipedia.org/wiki/JavaScript',
    docs: 'https://developer.mozilla.org/en-US/docs/Web/JavaScript',
  },
  'typescript': {
    wiki: 'https://en.wikipedia.org/wiki/TypeScript',
    docs: 'https://www.typescriptlang.org/docs/',
  },
  'go': {
    wiki: 'https://en.wikipedia.org/wiki/Go_(programming_language)',
    docs: 'https://go.dev/doc/',
  },
  'golang': {
    wiki: 'https://en.wikipedia.org/wiki/Go_(programming_language)',
    docs: 'https://go.dev/doc/',
  },
  'rust': {
    wiki: 'https://en.wikipedia.org/wiki/Rust_(programming_language)',
    docs: 'https://doc.rust-lang.org/book/',
  },
  'java': {
    wiki: 'https://en.wikipedia.org/wiki/Java_(programming_language)',
    docs: 'https://docs.oracle.com/en/java/',
  },
  'sql': {
    wiki: 'https://en.wikipedia.org/wiki/SQL',
  },
  'html': {
    wiki: 'https://en.wikipedia.org/wiki/HTML',
    docs: 'https://developer.mozilla.org/en-US/docs/Web/HTML',
  },
  'css': {
    wiki: 'https://en.wikipedia.org/wiki/CSS',
    docs: 'https://developer.mozilla.org/en-US/docs/Web/CSS',
  },

  // Frameworks & Libraries
  '.net': {
    wiki: 'https://en.wikipedia.org/wiki/.NET',
    docs: 'https://learn.microsoft.com/en-us/dotnet/',
  },
  'dotnet': {
    wiki: 'https://en.wikipedia.org/wiki/.NET',
    docs: 'https://learn.microsoft.com/en-us/dotnet/',
  },
  'asp.net': {
    wiki: 'https://en.wikipedia.org/wiki/ASP.NET',
    docs: 'https://learn.microsoft.com/en-us/aspnet/core/',
  },
  'asp.net core': {
    wiki: 'https://en.wikipedia.org/wiki/ASP.NET_Core',
    docs: 'https://learn.microsoft.com/en-us/aspnet/core/',
  },
  'react': {
    wiki: 'https://en.wikipedia.org/wiki/React_(JavaScript_library)',
    docs: 'https://react.dev/',
  },
  'reactjs': {
    wiki: 'https://en.wikipedia.org/wiki/React_(JavaScript_library)',
    docs: 'https://react.dev/',
  },
  'next.js': {
    wiki: 'https://en.wikipedia.org/wiki/Next.js',
    docs: 'https://nextjs.org/docs',
  },
  'nextjs': {
    wiki: 'https://en.wikipedia.org/wiki/Next.js',
    docs: 'https://nextjs.org/docs',
  },
  'node.js': {
    wiki: 'https://en.wikipedia.org/wiki/Node.js',
    docs: 'https://nodejs.org/docs/latest/api/',
  },
  'nodejs': {
    wiki: 'https://en.wikipedia.org/wiki/Node.js',
    docs: 'https://nodejs.org/docs/latest/api/',
  },
  'angular': {
    wiki: 'https://en.wikipedia.org/wiki/Angular_(web_framework)',
    docs: 'https://angular.dev/overview',
  },
  'vue': {
    wiki: 'https://en.wikipedia.org/wiki/Vue.js',
    docs: 'https://vuejs.org/guide/introduction',
  },
  'vuejs': {
    wiki: 'https://en.wikipedia.org/wiki/Vue.js',
    docs: 'https://vuejs.org/guide/introduction',
  },
  'vue.js': {
    wiki: 'https://en.wikipedia.org/wiki/Vue.js',
    docs: 'https://vuejs.org/guide/introduction',
  },
  'django': {
    wiki: 'https://en.wikipedia.org/wiki/Django_(web_framework)',
    docs: 'https://docs.djangoproject.com/',
  },
  'flask': {
    wiki: 'https://en.wikipedia.org/wiki/Flask_(web_framework)',
    docs: 'https://flask.palletsprojects.com/',
  },
  'fastapi': {
    wiki: 'https://en.wikipedia.org/wiki/FastAPI',
    docs: 'https://fastapi.tiangolo.com/',
  },
  'express': {
    wiki: 'https://en.wikipedia.org/wiki/Express.js',
    docs: 'https://expressjs.com/',
  },
  'expressjs': {
    wiki: 'https://en.wikipedia.org/wiki/Express.js',
    docs: 'https://expressjs.com/',
  },
  'spring boot': {
    wiki: 'https://en.wikipedia.org/wiki/Spring_Boot',
    docs: 'https://docs.spring.io/spring-boot/',
  },
  'tailwind': {
    wiki: 'https://en.wikipedia.org/wiki/Tailwind_CSS',
    docs: 'https://tailwindcss.com/docs',
  },
  'tailwind css': {
    wiki: 'https://en.wikipedia.org/wiki/Tailwind_CSS',
    docs: 'https://tailwindcss.com/docs',
  },
  'entity framework': {
    wiki: 'https://en.wikipedia.org/wiki/Entity_Framework',
    docs: 'https://learn.microsoft.com/en-us/ef/core/',
  },
  'ef core': {
    wiki: 'https://en.wikipedia.org/wiki/Entity_Framework',
    docs: 'https://learn.microsoft.com/en-us/ef/core/',
  },

  // Databases
  'postgresql': {
    wiki: 'https://en.wikipedia.org/wiki/PostgreSQL',
    docs: 'https://www.postgresql.org/docs/',
  },
  'postgres': {
    wiki: 'https://en.wikipedia.org/wiki/PostgreSQL',
    docs: 'https://www.postgresql.org/docs/',
  },
  'mysql': {
    wiki: 'https://en.wikipedia.org/wiki/MySQL',
    docs: 'https://dev.mysql.com/doc/',
  },
  'mongodb': {
    wiki: 'https://en.wikipedia.org/wiki/MongoDB',
    docs: 'https://www.mongodb.com/docs/',
  },
  'redis': {
    wiki: 'https://en.wikipedia.org/wiki/Redis',
    docs: 'https://redis.io/docs/',
  },
  'sqlite': {
    wiki: 'https://en.wikipedia.org/wiki/SQLite',
    docs: 'https://www.sqlite.org/docs.html',
  },
  'elasticsearch': {
    wiki: 'https://en.wikipedia.org/wiki/Elasticsearch',
    docs: 'https://www.elastic.co/guide/en/elasticsearch/reference/current/index.html',
  },

  // Infrastructure & DevOps
  'docker': {
    wiki: 'https://en.wikipedia.org/wiki/Docker_(software)',
    docs: 'https://docs.docker.com/',
  },
  'kubernetes': {
    wiki: 'https://en.wikipedia.org/wiki/Kubernetes',
    docs: 'https://kubernetes.io/docs/',
  },
  'k8s': {
    wiki: 'https://en.wikipedia.org/wiki/Kubernetes',
    docs: 'https://kubernetes.io/docs/',
  },
  'nginx': {
    wiki: 'https://en.wikipedia.org/wiki/Nginx',
    docs: 'https://nginx.org/en/docs/',
  },
  'rabbitmq': {
    wiki: 'https://en.wikipedia.org/wiki/RabbitMQ',
    docs: 'https://www.rabbitmq.com/docs',
  },
  'kafka': {
    wiki: 'https://en.wikipedia.org/wiki/Apache_Kafka',
    docs: 'https://kafka.apache.org/documentation/',
  },
  'aws': {
    wiki: 'https://en.wikipedia.org/wiki/Amazon_Web_Services',
    docs: 'https://docs.aws.amazon.com/',
  },
  'azure': {
    wiki: 'https://en.wikipedia.org/wiki/Microsoft_Azure',
    docs: 'https://learn.microsoft.com/en-us/azure/',
  },
  'linux': {
    wiki: 'https://en.wikipedia.org/wiki/Linux',
    docs: 'https://www.kernel.org/doc/',
  },
  'git': {
    wiki: 'https://en.wikipedia.org/wiki/Git',
    docs: 'https://git-scm.com/doc',
  },
  'github': {
    wiki: 'https://en.wikipedia.org/wiki/GitHub',
    docs: 'https://docs.github.com/',
  },
  'ci/cd': {
    wiki: 'https://en.wikipedia.org/wiki/CI/CD',
  },

  // Concepts & Patterns
  'microservices': {
    wiki: 'https://en.wikipedia.org/wiki/Microservices',
  },
  'mikroservis': {
    wiki: 'https://en.wikipedia.org/wiki/Microservices',
  },
  'rest api': {
    wiki: 'https://en.wikipedia.org/wiki/REST',
  },
  'restful': {
    wiki: 'https://en.wikipedia.org/wiki/REST',
  },
  'graphql': {
    wiki: 'https://en.wikipedia.org/wiki/GraphQL',
    docs: 'https://graphql.org/learn/',
  },
  'grpc': {
    wiki: 'https://en.wikipedia.org/wiki/GRPC',
    docs: 'https://grpc.io/docs/',
  },
  'websocket': {
    wiki: 'https://en.wikipedia.org/wiki/WebSocket',
    docs: 'https://developer.mozilla.org/en-US/docs/Web/API/WebSockets_API',
  },
  'cqrs': {
    wiki: 'https://en.wikipedia.org/wiki/Command_Query_Responsibility_Segregation',
    docs: 'https://learn.microsoft.com/en-us/azure/architecture/patterns/cqrs',
  },
  'clean architecture': {
    wiki: 'https://en.wikipedia.org/wiki/Software_architecture',
  },
  'domain driven design': {
    wiki: 'https://en.wikipedia.org/wiki/Domain-driven_design',
  },
  'ddd': {
    wiki: 'https://en.wikipedia.org/wiki/Domain-driven_design',
  },
  'tdd': {
    wiki: 'https://en.wikipedia.org/wiki/Test-driven_development',
  },
  'devops': {
    wiki: 'https://en.wikipedia.org/wiki/DevOps',
  },
  'agile': {
    wiki: 'https://en.wikipedia.org/wiki/Agile_software_development',
  },

  // AI & ML
  'machine learning': {
    wiki: 'https://en.wikipedia.org/wiki/Machine_learning',
  },
  'deep learning': {
    wiki: 'https://en.wikipedia.org/wiki/Deep_learning',
  },
  'artificial intelligence': {
    wiki: 'https://en.wikipedia.org/wiki/Artificial_intelligence',
  },
  'ai': {
    wiki: 'https://en.wikipedia.org/wiki/Artificial_intelligence',
  },
  'yapay zeka': {
    wiki: 'https://en.wikipedia.org/wiki/Artificial_intelligence',
  },
  'nlp': {
    wiki: 'https://en.wikipedia.org/wiki/Natural_language_processing',
  },
  'llm': {
    wiki: 'https://en.wikipedia.org/wiki/Large_language_model',
  },
  'rag': {
    wiki: 'https://en.wikipedia.org/wiki/Retrieval-augmented_generation',
  },
  'langchain': {
    wiki: 'https://en.wikipedia.org/wiki/LangChain',
    docs: 'https://python.langchain.com/docs/',
  },
  'chromadb': {
    wiki: 'https://en.wikipedia.org/wiki/Chroma_(vector_database)',
    docs: 'https://docs.trychroma.com/',
  },
  'ollama': {
    wiki: 'https://en.wikipedia.org/wiki/Ollama',
    docs: 'https://github.com/ollama/ollama/blob/main/docs/README.md',
  },

  // Other
  'signalr': {
    wiki: 'https://en.wikipedia.org/wiki/SignalR',
    docs: 'https://learn.microsoft.com/en-us/aspnet/core/signalr/',
  },
  'blazor': {
    wiki: 'https://en.wikipedia.org/wiki/Blazor',
    docs: 'https://learn.microsoft.com/en-us/aspnet/core/blazor/',
  },
  'oauth': {
    wiki: 'https://en.wikipedia.org/wiki/OAuth',
    docs: 'https://oauth.net/2/',
  },
  'jwt': {
    wiki: 'https://en.wikipedia.org/wiki/JSON_Web_Token',
    docs: 'https://jwt.io/introduction',
  },
  'json': {
    wiki: 'https://en.wikipedia.org/wiki/JSON',
    docs: 'https://www.json.org/',
  },
  'markdown': {
    wiki: 'https://en.wikipedia.org/wiki/Markdown',
    docs: 'https://commonmark.org/',
  },
  'yaml': {
    wiki: 'https://en.wikipedia.org/wiki/YAML',
    docs: 'https://yaml.org/spec/',
  },
  'prometheus': {
    wiki: 'https://en.wikipedia.org/wiki/Prometheus_(software)',
    docs: 'https://prometheus.io/docs/',
  },
  'grafana': {
    wiki: 'https://en.wikipedia.org/wiki/Grafana',
    docs: 'https://grafana.com/docs/',
  },
};

/**
 * Normalize: lowercase + trim
 */
function normalize(name: string): string {
  return name.toLowerCase().trim();
}

/**
 * Tag ve kategori isimlerini schema.org Thing entity'lerine cevirir.
 * Bilinen isimler sameAs olarak Wikipedia + resmi dokumantasyon URL'leri ile donulur.
 */
export function resolveEntities(
  tags?: { name: string }[],
  categories?: { name: string }[]
): SchemaEntity[] {
  const seen = new Set<string>();
  const entities: SchemaEntity[] = [];

  const items = [
    ...(categories?.map((c) => c.name) ?? []),
    ...(tags?.map((t) => t.name) ?? []),
  ];

  for (const name of items) {
    const key = normalize(name);
    if (seen.has(key)) continue;
    seen.add(key);

    const info = ENTITY_MAP[key];
    let sameAs: string | string[] | undefined;

    if (info) {
      sameAs = info.docs
        ? [info.wiki, info.docs]
        : info.wiki;
    }

    entities.push({
      '@type': 'Thing',
      name,
      ...(sameAs && { sameAs }),
    });
  }

  return entities;
}
