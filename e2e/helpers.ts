import { createHmac, randomUUID } from 'node:crypto';
import type { APIRequestContext } from '@playwright/test';

export const PASSWORD = 'E2eTest@2026';

function requireEnv(name: string): string {
  const value = process.env[name];
  if (!value) {
    throw new Error(`${name} is not set. See e2e/README.md (it must equal the target environment's value).`);
  }
  return value;
}

const b64 = (data: Buffer | string) => Buffer.from(data).toString('base64url');

// HS256 token signed the way auth_service signs its own, so the test can stand in for the
// inbox (verification link) and for an admin (cleanup) without any application change.
function signToken(payload: Record<string, unknown>): string {
  const now = Math.floor(Date.now() / 1000) - 60; // backdated: local clocks drift from the server's
  const body = { ...payload, iat: now, exp: now + 15 * 60 };
  const unsigned = `${b64(JSON.stringify({ alg: 'HS256', typ: 'JWT' }))}.${b64(JSON.stringify(body))}`;
  const sig = createHmac('sha256', requireEnv('SECRET_KEY')).update(unsigned).digest();
  return `${unsigned}.${b64(sig)}`;
}

export function verificationToken(userId: number, email: string): string {
  return signToken({ sub: String(userId), purpose: 'email_verification', email });
}

function adminHeaders() {
  return { Authorization: `Bearer ${signToken({ sub: '0', email: 'e2e@edura.lk', role: 'ADMIN' })}` };
}

/** A fresh address in Resend's test inbox: accepts any "+label", delivers nothing, never bounces. */
export function newEmail(): string {
  const user = process.env.SMOKE_EMAIL_USER || 'delivered';
  const domain = process.env.SMOKE_EMAIL_DOMAIN || 'resend.dev';
  return `${user}+e2e-${randomUUID().slice(0, 8)}@${domain}`;
}

export const apiUrl = (path: string) =>
  `${(process.env.STAGING_API_URL || process.env.STAGING_WEB_URL || 'https://staging.eduralms.com').replace(/\/+$/, '')}${path}`;

/** Registers and verifies a student through the API (setup for flows that start after sign-up). */
export async function createVerifiedStudent(request: APIRequestContext, email: string): Promise<number> {
  const res = await request.post(apiUrl('/api/auth/register'), {
    data: {
      email,
      password: PASSWORD,
      role: 'student',
      profile: {
        first_name: 'E2e',
        last_name: 'Student',
        mobile_no: '0771234567',
        school: 'E2E School',
        district: 'Colombo',
        grade: 6,
        selected_subjects: ['ICT'],
      },
    },
  });
  if (!res.ok()) throw new Error(`register failed: ${res.status()} ${await res.text()}`);
  const id: number = (await res.json()).id;
  await verifyEmail(request, id, email);
  return id;
}

export async function verifyEmail(request: APIRequestContext, userId: number, email: string): Promise<void> {
  const res = await request.post(apiUrl('/api/auth/verify-email'), {
    data: { token: verificationToken(userId, email) },
  });
  if (!res.ok()) throw new Error(`verify-email failed: ${res.status()} ${await res.text()}`);
}

/** Revokes a course enrolment through the admin API (kept as a CANCELLED record, as the admin UI does). */
export async function revokeEnrollment(request: APIRequestContext, userId: number | undefined, courseId: number): Promise<void> {
  if (!userId) return;
  await request
    .delete(apiUrl('/api/enrollments/admin/revoke'), { headers: adminHeaders(), params: { user_id: userId, course_id: courseId } })
    .catch(() => undefined);
}

/** Removes the test account and its profile; never throws, so a cleanup problem cannot hide a test result. */
export async function deleteStudent(request: APIRequestContext, userId: number | undefined): Promise<void> {
  if (!userId) return;
  for (const path of [`/api/users/${userId}`, `/api/auth/users/${userId}`]) {
    await request.delete(apiUrl(path), { headers: adminHeaders() }).catch(() => undefined);
  }
}
