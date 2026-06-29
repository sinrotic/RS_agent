import { HomeRecommendVO, HomeRecommendRequest, HomeRecommendRefreshRequest } from '../types/recommend';
import { isMockMode, postJson, mockDelay } from './shared';

// High quality mock recommendation items
export const MOCK_RECOMMEND_ITEMS = [
  {
    item_id: 'B08HEKJZ5S',
    rank: 1,
    score: 0.985,
    reason: '匹配您的通勤降噪诉求。在 200 美元价位中，其 ANC 降噪深度达到 -40dB，且拥有 30 小时超长续航。',
    source_tags: ['collaborative_filtering', 'category_hot', 'content_semantic'],
    display: {
      title: 'Sony WH-1000XM4 Wireless Noise Canceling Headphones',
      category: 'Audio / Headphones',
      store: 'Sony Electronics Store',
      image_url: 'https://images.unsplash.com/photo-1505740420928-5e560c06d30e?w=500&auto=format&fit=crop&q=60'
    }
  },
  {
    item_id: 'B09DFTCL5K',
    rank: 2,
    score: 0.923,
    reason: '近期人气数码配件，超便携无线蓝牙设计，拥有极佳的中低音回放能力，防尘防水。',
    source_tags: ['content_semantic', 'user_interest_cluster'],
    display: {
      title: 'JBL Flip 6 Portable Waterproof Bluetooth Speaker',
      category: 'Audio / Speakers',
      store: 'JBL Flagship Store',
      image_url: 'https://images.unsplash.com/photo-1608043152269-423dbba4e7e1?w=500&auto=format&fit=crop&q=60'
    }
  },
  {
    item_id: 'B07WM1HW89',
    rank: 3,
    score: 0.884,
    reason: '高性价比的选择，支持主动降噪与通透模式，完美适配日常运动与短途通勤。',
    source_tags: ['cold_fallback', 'popularity_score'],
    display: {
      title: 'Anker Soundcore Life Q30 Active Noise Cancelling Headphones',
      category: 'Audio / Headphones',
      store: 'Anker Direct',
      image_url: 'https://images.unsplash.com/photo-1546435770-a3e426bf472b?w=500&auto=format&fit=crop&q=60'
    }
  },
  {
    item_id: 'B08MT4SF3M',
    rank: 4,
    score: 0.851,
    reason: '轻巧紧凑的录音棚监听级入耳式耳机，高解析度发声单元，提供丰富的声音细节。',
    source_tags: ['collaborative_filtering'],
    display: {
      title: 'Sennheiser IE 300 High-Fidelity In-Ear Headphones',
      category: 'Audio / Headphones',
      store: 'Sennheiser Official',
      image_url: 'https://images.unsplash.com/photo-1618384887929-16ec33fab9ef?w=500&auto=format&fit=crop&q=60'
    }
  },
  {
    item_id: 'B07ZPC9NSS',
    rank: 5,
    score: 0.792,
    reason: '专业便携式数码无反相机，支持4K超高清视频摄制，是您拍摄Vlog与日常记录的绝佳礼物。',
    source_tags: ['user_interest_cluster'],
    display: {
      title: 'Sony Alpha ZV-1 Camera for Content Creators',
      category: 'Camera & Photo / Cameras',
      store: 'Sony Camera Store',
      image_url: 'https://images.unsplash.com/photo-1516035069371-29a1b244cc32?w=500&auto=format&fit=crop&q=60'
    }
  },
  {
    item_id: 'B085521HJZ',
    rank: 6,
    score: 0.751,
    reason: '复古拍立得相机，一键拍出怀旧相片，礼盒精美包装，适合作为赠予亲友的礼物。',
    source_tags: ['category_hot'],
    display: {
      title: 'Fujifilm Instax Mini 11 Instant Camera - Blush Pink',
      category: 'Camera & Photo / Instant Cameras',
      store: 'Fujifilm Flagship',
      image_url: 'https://images.unsplash.com/photo-1526170375885-4d8ecf77b99f?w=500&auto=format&fit=crop&q=60'
    }
  }
];

export async function recommendHome(req: HomeRecommendRequest): Promise<HomeRecommendVO> {
  if (isMockMode()) {
    await mockDelay(600);
    return {
      request_id: `req-${Math.random().toString(36).substring(2, 9)}`,
      session_id: `jsess-${Date.now()}`,
      scene: req.scene || 'home',
      profile_user_id: req.profileUserId,
      items: MOCK_RECOMMEND_ITEMS,
      has_more: false,
      next_cursor: '',
      config: {
        recall_pool_size: 500,
        coarse_rank_size: 100,
        fine_rank_size: 20,
        final_return_size: 6,
        first_screen_display_size: 6
      }
    };
  }

  // Real request to Java Endpoint: rs-service-recommend -> POST /api/recommend/home
  return postJson<HomeRecommendVO>('/recommend/home', req);
}

export async function refreshHome(req: HomeRecommendRefreshRequest): Promise<HomeRecommendVO> {
  if (isMockMode()) {
    await mockDelay(600);
    // Shuffle items to simulate a refresh
    const shuffled = [...MOCK_RECOMMEND_ITEMS].sort(() => Math.random() - 0.5);
    return {
      request_id: `req-${Math.random().toString(36).substring(2, 9)}`,
      session_id: req.sessionId,
      scene: req.scene || 'home',
      profile_user_id: req.profileUserId,
      items: shuffled,
      has_more: false,
      next_cursor: '',
      config: {
        recall_pool_size: 500,
        coarse_rank_size: 100,
        fine_rank_size: 20,
        final_return_size: 6,
        first_screen_display_size: 6
      }
    };
  }

  // Real request to Java Endpoint: rs-service-recommend -> POST /api/recommend/home/refresh
  return postJson<HomeRecommendVO>('/recommend/home/refresh', req);
}
