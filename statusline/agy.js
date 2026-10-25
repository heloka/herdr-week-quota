// Antigravity CLI status line: model + weekly quota used.
// Also hands the weekly quota to the herdr-week-quota plugin (herdr sidebar).
const fs = require('fs'), path = require('path');
let raw = '';
process.stdin.on('data', (c) => (raw += c));
process.stdin.on('end', () => {
  let d = {};
  try { d = JSON.parse(raw); } catch {}  const quota = d.quota || {};
  const model = String(d.model?.display_name || d.model?.id || '');
  const lower = model.toLowerCase();

  // Gemini and third-party models draw from separate pools; unknown models need a single pool.
  const pool = /gemini|flash|learnlm/.test(lower) ? 'gemini'
    : /claude|sonnet|haiku|opus|gpt|^o[134]/.test(lower) ? '3p' : null;
  const general = pool ? [`${pool}-weekly`] : ['gemini-weekly', '3p-weekly'].filter((k) => quota[k]);
  // Some models also have their own weekly pool, e.g. "gemini-argon-wtu-weekly" for Gemini 4 Argon.
  const words = lower.split(/[^a-z0-9]+/).filter((w) => w.length >= 3 && !['gemini', 'low', 'medium', 'high'].includes(w));
  const specific = Object.keys(quota).filter((k) => k.endsWith('-weekly') && !general.includes(k)
    && k.split('-').some((part) => words.includes(part)));
  const keys = [...(general.length === 1 ? general : []), ...specific];

  // Show the pool that runs out first.
  let week = null;
  for (const key of keys) {
    const bucket = quota[key];
    if (!bucket) continue;
    const pct = bucket.remaining_percent ?? bucket.remainingPercentage;
    const remaining = bucket.remaining_fraction ?? bucket.remainingFraction ?? (pct != null ? pct / 100 : null);
    const resetTime = bucket.reset_time || bucket.resetTime;
    const resetIn = bucket.reset_in_seconds ?? bucket.resetInSeconds;
    const resetsAt = resetTime ? Date.parse(resetTime) / 1000 : resetIn != null ? Date.now() / 1000 + Number(resetIn) : null;
    const used = remaining != null ? Math.round(100 - remaining * 100) : null;
    if (used != null && resetsAt && (!week || used > week.used_percentage)) week = { used_percentage: used, resets_at: resetsAt };
  }

  if (week && process.env.HERDR_PANE_ID && process.env.LOCALAPPDATA) {
    try {
      const dir = path.join(process.env.LOCALAPPDATA, 'herdr-week-quota', 'agy');
      fs.mkdirSync(dir, { recursive: true });
      const name = process.env.HERDR_PANE_ID.replace(/[^\w.-]/g, '_');
      fs.writeFileSync(path.join(dir, name + '.json'), JSON.stringify({ seven_day: week }));
    } catch {}
  }

  process.stdout.write(`${model}${week ? ` | 7d ${week.used_percentage}%` : ''}`);
});
