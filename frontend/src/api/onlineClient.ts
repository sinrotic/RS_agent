import type { RankRequest, RankingResponse, RecallRequest, RecallResponse, RecommendFromSequenceRequest, RecommendationResponse } from '../types';
import { postJson } from './shared';

export async function recommendFromSequence(request: RecommendFromSequenceRequest): Promise<RecommendationResponse> {
  return postJson<RecommendationResponse>('/recommend', request);
}

export async function recallCandidates(request: RecallRequest): Promise<RecallResponse> {
  return postJson<RecallResponse>('/recall', request);
}

export async function rankCandidates(request: RankRequest): Promise<RankingResponse> {
  return postJson<RankingResponse>('/rank', request);
}
