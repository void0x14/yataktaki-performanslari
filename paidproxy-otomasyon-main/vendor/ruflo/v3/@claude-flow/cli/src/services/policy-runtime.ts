/**
 * Ruflo compatibility seam.
 *
 * The standalone Security/Agent Federation packages are intentionally not
 * shipped in this integration. Core swarm and memory orchestration remains
 * available without a policy gate or an external security package.
 */

export type PolicyRequest = Record<string, unknown>;

export function classifyMcpTool(_toolName: string): string {
  return "orchestration";
}

export async function authorizeMcpTool(
  _toolName: string,
  _input: Record<string, unknown>,
  _context?: Record<string, unknown>,
  _category?: string,
): Promise<{ enforcedOutcome: "allowed"; reason: string; receiptId: string }> {
  return {
    enforcedOutcome: "allowed",
    reason: "ruflo security package omitted by project configuration",
    receiptId: "disabled",
  };
}

export async function autoMigratePolicyStateIfNeeded(_projectRoot = process.cwd()): Promise<{
  migrated: boolean;
  statePath?: string;
  mode?: "legacy";
}> {
  return { migrated: false, mode: "legacy" };
}

export async function evaluatePolicyRequest(
  request: PolicyRequest,
  _projectRoot = process.cwd(),
): Promise<Record<string, unknown>> {
  return { allowed: true, mode: "disabled", request };
}
