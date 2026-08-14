import { handleDropboxWebhook } from './handlers/webhooks/dropbox';
import {
  handleDropboxOAuthStart,
  handleDropboxOAuthCallback,
  handleDropboxConfigGet,
  handleDropboxConfigPost,
} from './handlers/admin/dropbox';
import { handlePublicDownloadsList, handlePublicDownloadRedirect } from './handlers/public/downloads';
import {
  handleAdminAuth,
  handleLogout,
  verifySession,
} from './handlers/admin/auth';
import { handleDownloadsPage } from './handlers/admin/pages';
import {
  handleApprovePending,
  handleRejectPending,
  handleArchivePublished,
} from './handlers/admin/downloads';

export interface Env {
  MEDIA: R2Bucket;
  DB: D1Database;
  RATELIMIT: KVNamespace;
  ADMIN_PATH: string;
  DROPBOX_APP_SECRET: string;
  ADMIN_PASSWORD_HASH: string;
  ADMIN_PASSWORD_PEPPER: string;
}

// Admin kimliği — oturum cookie'si (T11 şifre ile giriş sonrası)
async function getAdminEmail(request: Request, env: Env): Promise<string | null> {
  return verifySession(request, env);
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);
    const path = url.pathname;
    const adminBase = `/${env.ADMIN_PATH}`;

    // Sağlık kontrolü
    if (path === '/_health') {
      return new Response('ok', { status: 200 });
    }

    // Dropbox webhook
    if (path === '/api/webhooks/dropbox') {
      return handleDropboxWebhook(request, env, ctx);
    }

    // Public downloads API
    if (path === '/api/public/downloads') {
      return handlePublicDownloadsList(env);
    }

    if (path.startsWith('/api/public/download/') && request.method === 'GET') {
      const id = path.split('/').pop() || '';
      return handlePublicDownloadRedirect(request, env, id);
    }

    // Dropbox OAuth flow — admin oturumu gerekli
    if (path === `${adminBase}/dropbox/oauth/start`) {
      const email = await getAdminEmail(request, env);
      if (!email) {
        return new Response('Forbidden', { status: 403 });
      }
      return handleDropboxOAuthStart(env, email);
    }

    if (path === `${adminBase}/dropbox/oauth/callback`) {
      const email = await getAdminEmail(request, env);
      if (!email) {
        return new Response('Forbidden', { status: 403 });
      }
      return handleDropboxOAuthCallback(request, env, email);
    }

    if (path === `${adminBase}/dropbox/config` && request.method === 'GET') {
      const email = await getAdminEmail(request, env);
      if (!email) {
        return new Response('Forbidden', { status: 403 });
      }
      return handleDropboxConfigGet(env);
    }

    if (path === `${adminBase}/dropbox/config` && request.method === 'POST') {
      const email = await getAdminEmail(request, env);
      if (!email) {
        return new Response('Forbidden', { status: 403 });
      }
      return handleDropboxConfigPost(request, env, email);
    }

    // Downloads admin UI (T10)
    if (path === `${adminBase}/downloads` && request.method === 'GET') {
      const email = await getAdminEmail(request, env);
      if (!email) return new Response('Forbidden', { status: 403 });
      return handleDownloadsPage(env, email);
    }

    const approveMatch = path.match(new RegExp(`^/api/admin/download/pending/([0-9a-f-]{36})/approve$`));
    if (approveMatch && request.method === 'POST') {
      const email = await getAdminEmail(request, env);
      if (!email) return new Response('Forbidden', { status: 403 });
      return handleApprovePending(request, env, approveMatch[1], email);
    }

    const rejectMatch = path.match(new RegExp(`^/api/admin/download/pending/([0-9a-f-]{36})/reject$`));
    if (rejectMatch && request.method === 'POST') {
      const email = await getAdminEmail(request, env);
      if (!email) return new Response('Forbidden', { status: 403 });
      return handleRejectPending(request, env, rejectMatch[1], email);
    }

    const archiveMatch = path.match(new RegExp(`^/api/admin/download/published/([0-9a-f-]{36})/archive$`));
    if (archiveMatch && request.method === 'POST') {
      const email = await getAdminEmail(request, env);
      if (!email) return new Response('Forbidden', { status: 403 });
      return handleArchivePublished(request, env, archiveMatch[1], email);
    }

    // Admin şifre ile giriş (T11) — Google/Access kapısı yok; KV brute-force koruması
    if (path === `${adminBase}/admin-auth` && request.method === 'POST') {
      const ip = request.headers.get('CF-Connecting-IP') || 'unknown';
      const now = Date.now();
      const counter = await env.RATELIMIT.get(`login-attempts:${ip}`, 'json') as { count: number; window_start: number } | null;
      if (counter && counter.window_start > now - 15 * 60 * 1000 && counter.count >= 5) {
        return new Response('Too many attempts', { status: 429 });
      }
      const authRes = await handleAdminAuth(request, env, 'info@profixotomasyon.com.tr');
      if (authRes.status !== 200) {
        const c = counter && counter.window_start > now - 15 * 60 * 1000
          ? { count: counter.count + 1, window_start: counter.window_start }
          : { count: 1, window_start: now };
        await env.RATELIMIT.put(`login-attempts:${ip}`, JSON.stringify(c), { expirationTtl: 900 });
      } else {
        await env.RATELIMIT.delete(`login-attempts:${ip}`);
      }
      return authRes;
    }

    if (path === `${adminBase}/logout` && request.method === 'POST') {
      return handleLogout(request, env);
    }

    return new Response('Not Found', { status: 404 });
  },
};
