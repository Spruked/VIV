import { NextRequest, NextResponse } from 'next/server';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

function trimTrailingSlash(value: string): string {
  return value.trim().replace(/\/+$/, '');
}

function caliBase(): string {
  return trimTrailingSlash(process.env.CALI_API_URL || 'http://127.0.0.1:21000');
}

function adminToken(): string {
  return String(process.env.CALI_ADMIN_TOKEN || process.env.ADMIN_ACCESS_TOKEN || '').trim();
}

function contactTypeFromLeadType(value: string): string {
  const normalized = value.trim().toLowerCase();
  if (normalized === 'promoter') return 'promoter';
  if (normalized === 'investor') return 'investor';
  if (normalized === 'marketing') return 'marketing';
  if (normalized === 'business') return 'business';
  return 'marketing';
}

function waitlistRedirect(request: NextRequest, status: 'success' | 'error', detail?: string) {
  const url = new URL('/', request.url);
  url.hash = 'waitlist';
  url.searchParams.set('waitlist', status);
  if (detail) {
    url.searchParams.set('detail', detail);
  }
  return NextResponse.redirect(url);
}

export async function POST(request: NextRequest) {
  try {
    const formData = await request.formData();
    const email = String(formData.get('email') || formData.get('waitlistEmail') || '').trim().toLowerCase();
    const leadType = String(formData.get('leadType') || 'marketing').trim();
    const source = String(formData.get('source') || 'homepage_waitlist').trim();

    if (!email || !email.includes('@')) {
      return waitlistRedirect(request, 'error', 'invalid_email');
    }

    const token = adminToken();
    if (!token) {
      return waitlistRedirect(request, 'error', 'admin_token_missing');
    }

    const localName = email.split('@')[0] || email;
    const payload = {
      name: `Waitlist Lead: ${localName}`,
      contact_type: contactTypeFromLeadType(leadType),
      crm_stage: 'prospect',
      lead_source: source,
      email,
      notes: `source=${source}; role=${leadType}; captured_by=homepage_waitlist`,
      priority: leadType.toLowerCase() === 'investor' ? 2 : 1,
    };

    const response = await fetch(`${caliBase()}/cali/contacts`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify(payload),
      cache: 'no-store',
    });

    if (!response.ok) {
      return waitlistRedirect(request, 'error', 'storage_failed');
    }

    return waitlistRedirect(request, 'success');
  } catch {
    return waitlistRedirect(request, 'error', 'unexpected_error');
  }
}
