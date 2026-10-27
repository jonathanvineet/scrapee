// get_context returns blocks of "## title\n[SOURCE: url]\n\npassage\n\n```lang\ncode\n```".
export function parseContext(context) {
  if (!context || context === 'No context available') return [];
  return context.split('\n\n---\n\n').map((block) => {
    const title = (block.match(/^## (.*)$/m) || [])[1] || '';
    const url = (block.match(/^\[SOURCE: (.*)\]$/m) || [])[1] || '';
    const code = [...block.matchAll(/```(\w*)\n([\s\S]*?)\n```/g)].map((m) => ({ lang: m[1], text: m[2] }));
    const passage = block
      .replace(/^## .*$/m, '')
      .replace(/^\[SOURCE: .*\]$/m, '')
      .replace(/```\w*\n[\s\S]*?\n```/g, '')
      .trim();
    return { title, url, passage, code };
  });
}

const STOP = new Set(['a', 'an', 'and', 'are', 'how', 'i', 'in', 'is', 'it', 'of', 'on', 'or', 'the', 'to', 'use', 'what', 'with', 'do', 'does', 'my', 'for']);

export function queryTerms(query) {
  return (query || '')
    .toLowerCase()
    .split(/[^a-z0-9_]+/)
    .filter((t) => t.length > 1 && !STOP.has(t));
}
