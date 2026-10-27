const nf = new Intl.NumberFormat('en-US');

export const n = (value) => nf.format(value || 0);

export const plural = (count, one, many = `${one}s`) => `${n(count)} ${count === 1 ? one : many}`;

// "Today", "Yesterday", "6 days ago", then an ISO date for anything older.
export function since(iso) {
  if (!iso) return '—';
  const then = new Date(iso.endsWith('Z') || iso.includes('+') ? iso : `${iso}Z`);
  if (Number.isNaN(then.getTime())) return '—';
  const days = Math.floor((Date.now() - then.getTime()) / 86400000);
  if (days <= 0) return 'Today';
  if (days === 1) return 'Yesterday';
  if (days < 14) return `${days} days ago`;
  return then.toISOString().slice(0, 10);
}

export function pathOf(url) {
  try {
    const u = new URL(url);
    return (u.pathname + u.hash).replace(/\/$/, '') || '/';
  } catch {
    return url;
  }
}

export function normaliseUrl(raw) {
  const value = raw.trim();
  if (!value) return '';
  return /^https?:\/\//i.test(value) ? value : `https://${value}`;
}
