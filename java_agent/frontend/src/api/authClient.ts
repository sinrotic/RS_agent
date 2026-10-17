import { RegisterRequest, LoginRequest, AuthTokenVO, CurrentAccountVO } from '../types/auth';
import {
  clearTokens,
  getJson,
  isMockMode,
  mockDelay,
  postJson,
  saveMockAccessToken,
  saveRealAccessToken,
  saveStoredProfileUserId,
  saveAccountId,
  captureAuthSession,
  assertCurrentAuthSession,
  invalidateAuthSession,
  isCurrentAuthSession,
} from './shared';

// For local mockup mock-users databases
const MOCK_USER_KEY = 'rs_mock_users';
const CURRENT_MOCK_USER_KEY = 'rs_current_mock_user';
type MockUser = Omit<AuthTokenVO, 'accessToken' | 'refreshToken'>;

function getMockUsers(): Record<string, MockUser> {
  const users = localStorage.getItem(MOCK_USER_KEY);
  return users ? JSON.parse(users) : {};
}

function safeMockUser(user: AuthTokenVO): MockUser {
  return {
    accountId: user.accountId,
    username: user.username,
    nickname: user.nickname,
    profileUserId: user.profileUserId,
    profileSummary: user.profileSummary,
    expiresIn: user.expiresIn,
  };
}

function saveMockUser(username: string, user: AuthTokenVO) {
  const users = getMockUsers();
  users[username] = safeMockUser(user);
  localStorage.setItem(MOCK_USER_KEY, JSON.stringify(users));
}

function issueMockToken(user: MockUser): AuthTokenVO {
  return {
    ...user,
    accessToken: `mock-access-token-${user.username}-${Date.now()}`,
  };
}

export async function register(req: RegisterRequest): Promise<AuthTokenVO> {
  clearTokens();
  const session = captureAuthSession();
  if (isMockMode()) {
    await mockDelay(500);
    assertCurrentAuthSession(session);
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
      expiresIn: 1800,
    };
    saveMockUser(username, tokenVO);
    saveMockAccessToken(tokenVO.accessToken);
    saveAccountId(tokenVO.accountId);
    saveStoredProfileUserId(tokenVO.profileUserId);
    localStorage.setItem(CURRENT_MOCK_USER_KEY, JSON.stringify(safeMockUser(tokenVO)));
    return tokenVO;
  }

  // Real request to Java Endpoint: rs-service-user -> /api/auth/register
  const res = await postJson<AuthTokenVO>('/auth/register', req);
  assertCurrentAuthSession(session);
  saveRealAccessToken(res.accessToken);
  saveAccountId(res.accountId);
  saveStoredProfileUserId(res.profileUserId);
  return res;
}

export async function login(req: LoginRequest): Promise<AuthTokenVO> {
  clearTokens();
  const session = captureAuthSession();
  if (isMockMode()) {
    await mockDelay(500);
    assertCurrentAuthSession(session);
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
        expiresIn: 1800,
      };
      saveMockUser(username, tokenVO);
      saveMockAccessToken(tokenVO.accessToken);
      saveAccountId(tokenVO.accountId);
      saveStoredProfileUserId(tokenVO.profileUserId);
      localStorage.setItem(CURRENT_MOCK_USER_KEY, JSON.stringify(safeMockUser(tokenVO)));
      return tokenVO;
    }
    const tokenVO = issueMockToken(user);
    saveMockAccessToken(tokenVO.accessToken);
    saveAccountId(tokenVO.accountId);
    saveStoredProfileUserId(tokenVO.profileUserId);
    localStorage.setItem(CURRENT_MOCK_USER_KEY, JSON.stringify(user));
    return tokenVO;
  }

  // Real request to Java Endpoint: rs-service-user -> /api/auth/login
  const res = await postJson<AuthTokenVO>('/auth/login', req);
  assertCurrentAuthSession(session);
  saveRealAccessToken(res.accessToken);
  saveAccountId(res.accountId);
  saveStoredProfileUserId(res.profileUserId);
  return res;
}

export async function getMe(): Promise<CurrentAccountVO> {
  const session = captureAuthSession();
  if (isMockMode()) {
    await mockDelay(200);
    assertCurrentAuthSession(session);
    const current = localStorage.getItem(CURRENT_MOCK_USER_KEY);
    if (!current) throw new Error('未登录');
    const user = JSON.parse(current) as MockUser;
    saveAccountId(user.accountId);
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
  const user = await getJson<CurrentAccountVO>('/auth/me');
  assertCurrentAuthSession(session);
  saveAccountId(user.accountId);
  return user;
}

export async function logout(): Promise<void> {
  if (isMockMode()) {
    clearTokens();
    localStorage.removeItem(CURRENT_MOCK_USER_KEY);
    return;
  }

  const session = invalidateAuthSession();
  // Real request to Java Endpoint: rs-service-user -> /api/auth/logout
  try {
    await postJson('/auth/logout', {});
  } finally {
    if (isCurrentAuthSession(session)) clearTokens();
  }
}
