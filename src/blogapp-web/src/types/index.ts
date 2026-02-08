// User types
export interface User {
  id: string;
  userName: string;
  email: string;
  fullName: string;
  avatarUrl?: string;
  role: string;
}

export interface AuthResponse {
  accessToken: string;
  refreshToken: string;
  expiresAt: string;
  user: User;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface RegisterRequest {
  userName: string;
  email: string;
  password: string;
  confirmPassword: string;
  firstName?: string;
  lastName?: string;
}

// Post types
export interface BlogPost {
  id: string;
  title: string;
  slug: string;
  excerpt: string;
  content: string;
  featuredImageUrl?: string;
  status: PostStatus;
  viewCount: number;
  publishedAt?: string;
  createdAt: string;
  updatedAt?: string;
  author: Author;
  category?: Category;
  categories?: Category[];
  tags: Tag[];
  // AI-generated fields
  aiSummary?: string;
  aiKeywords?: string;
  aiEstimatedReadingTime?: number;
  aiSeoDescription?: string;
  aiProcessedAt?: string;
  aiGeoOptimization?: string;
}

// AI Summary Response
export interface AISummaryResponse {
  summary: string;
  wordCount: number;
}

export interface Author {
  id: string;
  userName: string;
  fullName: string;
  avatarUrl?: string;
}

export type PostStatus = 'Draft' | 'Published' | 'Archived';

export interface CreatePostRequest {
  title: string;
  content: string;
  excerpt: string;
  featuredImageUrl?: string;
  categoryIds: string[];
  tagNames: string[];
  status: PostStatus;
}

export interface UpdatePostRequest extends CreatePostRequest {
  id: string;
  // AI-generated fields
  aiSummary?: string;
  aiKeywords?: string;
  aiEstimatedReadingTime?: number;
  aiSeoDescription?: string;
  aiGeoOptimization?: string;
}

// Category types
export interface Category {
  id: string;
  name: string;
  slug: string;
  description?: string;
  postCount?: number;
}

export interface CreateCategoryRequest {
  name: string;
  description?: string;
}

// Tag types
export interface Tag {
  id: string;
  name: string;
  slug: string;
  postCount?: number;
}

export interface CreateTagRequest {
  name: string;
}

// Comment types
export interface Comment {
  id: string;
  content: string;
  authorName: string;
  authorEmail?: string;
  avatarUrl?: string;
  isApproved: boolean;
  createdAt: string;
  updatedAt?: string;
  userId?: string;
  parentCommentId?: string;
  replies?: Comment[];
}

export interface CreateCommentRequest {
  postId: string;
  content: string;
  authorName?: string;
  authorEmail?: string;
  parentCommentId?: string;
}

// Pagination types
export interface PaginatedResult<T> {
  items: T[];
  pageNumber: number;
  pageSize: number;
  totalCount: number;
  totalPages: number;
  hasPreviousPage: boolean;
  hasNextPage: boolean;
}

export interface PaginationParams {
  pageNumber?: number;
  pageSize?: number;
}

// API Response types
export interface ApiResponse<T> {
  data?: T;
  success: boolean;
  message?: string;
  errors?: string[];
}

// AI types
export interface AISuggestion {
  title?: string;
  excerpt?: string;
  tags?: string[];
  seoDescription?: string;
}

export interface AIGenerateRequest {
  content: string;
  type: 'title' | 'excerpt' | 'tags' | 'seo';
}

// Media types
export interface ImageUploadResult {
  url: string;
  thumbnailUrl?: string;
  width: number;
  height: number;
  fileSize: number;
  contentType: string;
}

// Chat types
export type AgentType = 'normal' | 'summary' | 'web-search';

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  agentType?: AgentType;
  isWebSearchResult?: boolean;
  sources?: WebSearchSource[];
  timestamp: Date;
}

export interface WebSearchSource {
  title: string;
  url: string;
  snippet: string;
}

export interface ChatRequest {
  postId: string;
  message: string;
  sessionId?: string;
  conversationHistory?: ChatHistoryItem[];
  language?: string;
  enableWebSearch?: boolean;
}

export interface ChatHistoryItem {
  role: 'user' | 'assistant';
  content: string;
}

export interface ChatResponse {
  correlationId: string;
  sessionId: string;
  message: string;
}

export interface ChatMessageReceivedEvent {
  sessionId: string;
  correlationId: string;
  response: string;
  isWebSearchResult: boolean;
  sources?: WebSearchSource[];
  timestamp: string;
}
