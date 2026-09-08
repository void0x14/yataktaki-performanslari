declare module '@claude-flow/security' {
  export class SafeExecutor {
    constructor(options?: unknown);
    execute(command: string, args?: string[]): Promise<{ exitCode: number; stdout: string; stderr: string }>;
  }
  export class PathValidator {
    constructor(options?: unknown);
    validate(path: string): Promise<{ isValid: boolean; errors?: string[] }>;
  }
  export function createKeychainAdapter(): Promise<{ isAvailable(): Promise<boolean> }>;
}
