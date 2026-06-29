import { RegisterRequest, LoginRequest, AuthTokenVO, CurrentAccountVO } from '../types/auth';
import { isMockMode, postJson, getJson, saveTokens, saveStoredProfileUserId, clearTokens, mockDelay } from './shared';

// For local mockup mock-users databases
const MOCK_USER_KEY = 'rs_mock_users';
const CURRENT_MOCK_USER_KEY = 'rs_current_mock_user';

function getMockUsers(): Record<string, AuthTokenVO> {
  const users = localStorage.getItem(MOCK_USER_KEY);
  return users ? JSON.parse(users) : {};
}

function saveMockUser(username: string, user: AuthTokenVO) {
  const users = getMockUsers();
  users[username] = user;
  localStorage.setItem(MOCK_USER_KEY, JSON.stringify(users));
}

export async function register(req: RegisterRequest): Promise<AuthTokenVO> {
  if (isMockMode()) {
    await mockDelay(500);
    const username = req.username.trim();
    if (!username) throw new Error('用户名不能为空');
    const users = getMockUsers();
    if (users[username]) {
      throw new Error('用户名已存在');
    }
    const profileUserId = req.profileUserId || `user_${Math.floor(Math.random() * 1000) + 1000}`;
    const tokenVO: AuthTokenVO = {
      accountId: `acc_${Math.random().toString(36).substring(2, 9)}`,
      username,
      nickname: req.nickname || username,
      profileUserId,
      profileSummary: `画像分配策略: ${req.bindStrategy || 'random'}, 人群分组: ${req.segment || 'default'}`,
      accessToken: `mock-access-token-${username}-${Date.now()}`,
      refreshToken: `mock-refresh-token-${username}-${Date.now()}`,
      expiresIn: 1800,
    };
    saveMockUser(username, tokenVO);
    saveTokens(tokenVO.accessToken, tokenVO.refreshToken);
    saveStoredProfileUserId(tokenVO.profileUserId);
    localStorage.setItem(CURRENT_MOCK_USER_KEY, JSON.stringify(tokenVO));
    return tokenVO;
  }

  // Real request to Java Endpoint: rs-service-user -> /api/auth/register
  const res = await postJson<AuthTokenVO>('/auth/register', req);
  saveTokens(res.accessToken, res.refreshToken);
  saveStoredProfileUserId(res.profileUserId);
  return res;
}

export async function login(req: LoginRequest): Promise<AuthTokenVO> {
  if (isMockMode()) {
    await mockDelay(500);
    const username = req.username.trim();
    const users = getMockUsers();
    const user = users[username];
    if (!user) {
      // Create a mock user on the fly if not exists (for developer convenience)
      const profileUserId = `user_${Math.floor(Math.random() * 1000) + 1000}`;
      const tokenVO: AuthTokenVO = {
        accountId: `acc_${Math.random().toString(36).substring(2, 9)}`,
        username,
        nickname: username,
        profileUserId,
        profileSummary: '自动生成的临时画像账户',
        accessToken: `mock-access-token-${username}-${Date.now()}`,
        refreshToken: `mock-refresh-token-${username}-${Date.now()}`,
        expiresIn: 1800,
      };
      saveMockUser(username, tokenVO);
      saveTokens(tokenVO.accessToken, tokenVO.refreshToken);
      saveStoredProfileUserId(tokenVO.profileUserId);
      localStorage.setItem(CURRENT_MOCK_USER_KEY, JSON.stringify(tokenVO));
      return tokenVO;
    }
    saveTokens(user.accessToken, user.refreshToken);
    saveStoredProfileUserId(user.profileUserId);
    localStorage.setItem(CURRENT_MOCK_USER_KEY, JSON.stringify(user));
    return user;
  }

  // Real request to Java Endpoint: rs-service-user -> /api/auth/login
  const res = await postJson<AuthTokenVO>('/auth/login', req);
  saveTokens(res.accessToken, res.refreshToken);
  saveStoredProfileUserId(res.profileUserId);
  return res;
}

export async function getMe(): Promise<CurrentAccountVO> {
  if (isMockMode()) {
    await mockDelay(200);
    const current = localStorage.getItem(CURRENT_MOCK_USER_KEY);
    if (!current) throw new Error('未登录');
    const user = JSON.parse(current) as AuthTokenVO;
    return {
      accountId: user.accountId,
      username: user.username,
      nickname: user.nickname,
      profileUserId: user.profileUserId,
      profile: {
        profileUserId: user.profileUserId,
        segment: 'Smart Tech Commuters',
        gender: 'M',
        ageGroup: '25-34',
        occupation: 'Software Engineer',
        city: 'Shanghai',
        interestTags: ['Audio', 'Headphones', 'Gadgets', 'Bluetooth']
      }
    };
  }

  // Real request to Java Endpoint: rs-service-user -> /api/auth/me
  return getJson<CurrentAccountVO>('/auth/me');
}

export async function logout(): Promise<void> {
  if (isMockMode()) {
    clearTokens();
    localStorage.removeItem(CURRENT_MOCK_USER_KEY);
    return;
  }

  // Real request to Java Endpoint: rs-service-user -> /api/auth/logout
  try {
    await postJson('/auth/logout', {});
  } finally {
    clearTokens();
  }
}
