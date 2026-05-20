export interface User {
  id: number;
  email: string;
  full_name: string;
  is_active: boolean;
  created_at: string;
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export interface Document {
  document_id: string;
  filename: string;
  source_type: string;
  status: "pending" | "processing" | "ready" | "failed";
  chunks_count: number;
  file_size_bytes: number;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface SourceReference {
  chunk_id: string;
  source: string;
  page: number | null;
  score: number;
}

export interface QueryResponse {
  answer: string;
  sources: SourceReference[];
  model: string;
  prompt_tokens: number;
  completion_tokens: number;
  question: string;
}

export interface Message {
  message_id: string;
  role: "user" | "assistant";
  content: string;
  prompt_tokens: number;
  completion_tokens: number;
  created_at: string;
}

export interface Conversation {
  conversation_id: string;
  title: string;
  document_id: string | null;
  created_at: string;
  updated_at: string;
  message_count: number;
  messages?: Message[];
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources?: SourceReference[];
  streaming?: boolean;
}
