// Claude Code status line: model + weekly quota used.
// Also hands rate limits to the herdr-week-quota plugin (herdr sidebar).
const fs = require('fs'), path = require('path');
let raw = '';
process.stdin.on('data', (c) => (raw += c));
process.stdin.on('end', () => {
  let d = {};
  try { d = JSON.parse(raw); } catch {}

  if (d.rate_limits && d.session_id && process.env.LOCALAPPDATA) {
    try {
      const dir = path.join(process.env.LOCALAPPDATA, 'herdr-week-quota', 'claude');
      fs.mkdirSync(dir, { recursive: true });
      fs.writeFileSync(path.join(dir, d.session_id + '.json'), JSON.stringify(d.rate_limits));
    } catch {}
  }

  const used = d.rate_limits?.seven_day?.used_percentage;
  process.stdout.write(`${d.model?.display_name || ''}${used != null ? ` | 7d ${Math.round(used)}%` : ''}`);
});
