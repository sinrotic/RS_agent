export interface RegisterRequest {
  username: string;
  password?: string; // Optional if auto-registering or handled on login
  nickname?: string;
  bindStrategy?: 'random' | 'manual' | 'segment';
  profileUserId?: string;
  segment?: string;
}

export interface LoginRequest {
  username: string;
  password?: string;
}

export interface RefreshTokenRequest {
  refreshToken: string;
}

export interface UserProfileVO {
  profileUserId: string;
  segment: string;
  gender: string;
  ageGroup: string;
  occupation: string;
  city: string;
  interestTags: string[];
}

export interface AuthTokenVO {
  accountId: string;
  username: string;
  nickname: string;
  profileUserId: string;
  profileSummary: string;
  accessToken: string;
  refreshToken: string;
  expiresIn: number;
}

export interface CurrentAccountVO {
  accountId: string;
  username: string;
  nickname: string;
  profileUserId: string;
  profile?: UserProfileVO;
}
