export function escapeHtml(str) {
  if (typeof str !== "string") return str;
  return str.replace(/[&<>"']/g, m => {
    switch (m) {
      case '&': return '&amp;';
      case '<': return '&lt;';
      case '>': return '&gt;';
      case '"': return '&quot;';
      case "'": return '&#39;';
      default: return m;
    }
  });
}

export function channelKey(cfg, index) {
  return cfg.channel_username ? `@${cfg.channel_username}` : `index_${index}`;
}

export function channelTitle(username) {
  return `@${username.replace(/^@/, "")}`;
}
