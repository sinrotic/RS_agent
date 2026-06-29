export interface RecommendDisplayVO {
  title: string;
  category: string;
  store: string;
  image_url: string;
}

export interface RecommendItemVO {
  item_id: string;
  rank: number;
  score: number;
  reason: string;
  source_tags: string[];
  display: RecommendDisplayVO;
}

export interface HomeRecommendConfigVO {
  recall_pool_size: number;
  coarse_rank_size: number;
  fine_rank_size: number;
  final_return_size: number;
  first_screen_display_size: number;
}

export interface HomeRecommendVO {
  request_id: string;
  session_id: string;
  scene: string;
  profile_user_id: string;
  items: RecommendItemVO[];
  has_more: boolean;
  next_cursor: string;
  config?: HomeRecommendConfigVO;
}

export interface HomeRecommendRequest {
  profileUserId: string;
  scene?: string;
  limit?: number;
  cursor?: string;
  debug?: boolean;
}

export interface HomeRecommendRefreshRequest {
  sessionId: string;
  profileUserId: string;
  scene?: string;
  limit?: number;
  cursor?: string;
  debug?: boolean;
  refreshAction?: string;
}

export interface AgentRecommendCandidatesVO {
  request_id: string;
  agent_id: string;
  task_id: string;
  profile_user_id: string;
  candidates: RecommendItemVO[];
}

export interface AgentRecommendCandidatesRequest {
  profileUserId: string;
  agentId: string;
  taskId: string;
  scene?: string;
  limit?: number;
  debug?: boolean;
}
