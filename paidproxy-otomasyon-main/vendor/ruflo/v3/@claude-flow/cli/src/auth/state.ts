export type RufloProfile = {
  profile: string;
  scopes: string[];
  keychainRef?: string;
  accessTokenExpiresAt?: number;
};

export function listProfiles(): { profiles: RufloProfile[]; defaultProfile?: string } {
  return { profiles: [], defaultProfile: undefined };
}

export function getProfile(_profile?: string): RufloProfile | undefined {
  return undefined;
}
