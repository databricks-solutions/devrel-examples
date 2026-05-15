import { useEffect, useMemo, useState } from 'react';
import { Badge, Card, CardContent, CardHeader, CardTitle, Skeleton } from '@databricks/appkit-ui/react';

interface ManualSummary {
  slug: string;
  title: string;
  bytes: number;
}

interface ManualBody {
  slug: string;
  title: string;
  markdown: string;
}

export function DocsPage() {
  const [manuals, setManuals] = useState<ManualSummary[]>([]);
  const [activeSlug, setActiveSlug] = useState<string | null>(null);
  const [body, setBody] = useState<ManualBody | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch('/api/docs/manuals')
      .then((res) => {
        if (!res.ok) throw new Error(`Failed to list manuals: ${res.status}`);
        return res.json() as Promise<ManualSummary[]>;
      })
      .then((rows) => {
        setManuals(rows);
        if (rows.length > 0) setActiveSlug(rows[0].slug);
      })
      .catch((err) => setError(err instanceof Error ? err.message : 'Failed to load manuals'))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!activeSlug) return;
    fetch(`/api/docs/manuals/${activeSlug}`)
      .then((res) => res.json() as Promise<ManualBody>)
      .then(setBody)
      .catch((err) => setError(err instanceof Error ? err.message : 'Failed to load manual'));
  }, [activeSlug]);

  const rendered = useMemo(() => (body ? renderMarkdown(body.markdown) : ''), [body]);

  if (loading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-10 w-72" />
        <Skeleton className="h-[600px] w-full" />
      </div>
    );
  }

  return (
    <div className="rounded-3xl border border-amber-500/20 bg-[radial-gradient(circle_at_20%_0%,rgba(245,158,11,0.18),transparent_32%),linear-gradient(135deg,#07040d,#111827_48%,#1b1026)] p-5 text-slate-100 shadow-2xl">
      <section className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-sm uppercase tracking-[0.28em] text-amber-300">Operations corpus</p>
          <h2 className="text-3xl font-bold text-white">Manuals & narratives</h2>
          <p className="max-w-3xl text-sm text-slate-300">
            Educational content describing how a slot floor team interprets the events the simulator emits.
            Eventually indexed by a Knowledge Assistant in the Databricks app — for now, raw markdown.
          </p>
        </div>
        <Badge variant="outline" className="border-amber-300/60 text-amber-200">
          {manuals.length} document{manuals.length === 1 ? '' : 's'}
        </Badge>
      </section>

      {error && (
        <Card className="mt-4 border-rose-500/30 bg-slate-950/80">
          <CardHeader>
            <CardTitle className="text-rose-200">Docs unavailable</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-rose-300">{error}</p>
          </CardContent>
        </Card>
      )}

      <section className="mt-5 grid gap-4 xl:grid-cols-[260px_minmax(0,1fr)]">
        <Card className="border-amber-500/20 bg-slate-950/90 text-slate-100">
          <CardHeader>
            <CardTitle className="text-sm">Corpus</CardTitle>
          </CardHeader>
          <CardContent className="space-y-1.5 p-3">
            {manuals.map((m) => (
              <button
                key={m.slug}
                type="button"
                onClick={() => setActiveSlug(m.slug)}
                className={`flex w-full items-center justify-between rounded-md border px-3 py-2 text-left text-sm transition-colors ${
                  activeSlug === m.slug
                    ? 'border-amber-400/60 bg-amber-500/10 text-amber-100'
                    : 'border-slate-800 bg-slate-900/50 text-slate-200 hover:border-amber-400/40 hover:bg-amber-500/5'
                }`}
              >
                <span className="font-medium">{m.title}</span>
                <span className="ml-2 text-[10px] text-slate-500">{(m.bytes / 1024).toFixed(1)} KB</span>
              </button>
            ))}
          </CardContent>
        </Card>

        <Card className="border-amber-500/20 bg-slate-950/90 text-slate-100">
          <CardHeader className="border-b border-amber-500/15">
            <CardTitle>{body?.title ?? 'Select a manual'}</CardTitle>
          </CardHeader>
          <CardContent className="prose-invert max-w-none p-5 text-sm leading-relaxed">
            {body ? (
              <div className="docs-markdown" dangerouslySetInnerHTML={{ __html: rendered }} />
            ) : (
              <p className="text-slate-400">Pick a document on the left.</p>
            )}
          </CardContent>
        </Card>
      </section>
    </div>
  );
}

// Tiny, safe-enough markdown renderer for the demo corpus. Supports headings,
// fenced code blocks, lists, tables, inline code, links, and bold/italic.
// All HTML metacharacters in the source are escaped before transformation so
// the markdown can be inserted via dangerouslySetInnerHTML.
function renderMarkdown(src: string): string {
  const escapedLines: string[] = [];
  const codeBlocks: string[] = [];
  let inCode = false;
  let codeBuffer: string[] = [];
  for (const rawLine of src.split('\n')) {
    if (rawLine.trim().startsWith('```')) {
      if (inCode) {
        codeBlocks.push(codeBuffer.join('\n'));
        escapedLines.push(`<<CODE_BLOCK_${codeBlocks.length - 1}>>`);
        codeBuffer = [];
        inCode = false;
      } else {
        inCode = true;
      }
      continue;
    }
    if (inCode) {
      codeBuffer.push(rawLine);
    } else {
      escapedLines.push(escapeHtml(rawLine));
    }
  }

  // Tables
  const blocks: string[] = [];
  let i = 0;
  while (i < escapedLines.length) {
    const line = escapedLines[i];
    if (line.startsWith('| ') && i + 1 < escapedLines.length && /^\|\s*[-:|\s]+\|\s*$/.test(escapedLines[i + 1])) {
      const headerCells = line.split('|').slice(1, -1).map((c) => c.trim());
      const rows: string[][] = [];
      i += 2;
      while (i < escapedLines.length && escapedLines[i].startsWith('| ')) {
        rows.push(escapedLines[i].split('|').slice(1, -1).map((c) => c.trim()));
        i += 1;
      }
      const head = `<thead><tr>${headerCells.map((c) => `<th>${c}</th>`).join('')}</tr></thead>`;
      const body = `<tbody>${rows.map((r) => `<tr>${r.map((c) => `<td>${inlineMd(c)}</td>`).join('')}</tr>`).join('')}</tbody>`;
      blocks.push(`<table>${head}${body}</table>`);
      continue;
    }
    blocks.push(line);
    i += 1;
  }

  const joined = blocks.join('\n');

  // Headings & paragraphs & lists
  const html = joined
    .replace(/^###\s+(.+)$/gm, '<h3>$1</h3>')
    .replace(/^##\s+(.+)$/gm, '<h2>$1</h2>')
    .replace(/^#\s+(.+)$/gm, '<h1>$1</h1>')
    .replace(/^(- .+(?:\n- .+)*)/gm, (match) => {
      const items = match
        .split('\n')
        .map((l) => `<li>${inlineMd(l.replace(/^- /, ''))}</li>`)
        .join('');
      return `<ul>${items}</ul>`;
    })
    .replace(/^>\s+(.+)$/gm, '<blockquote>$1</blockquote>')
    .split('\n\n')
    .map((para) => {
      if (
        /^<(h\d|ul|table|blockquote|<<CODE_BLOCK_)/.test(para.trim()) ||
        para.trim() === ''
      ) {
        return para;
      }
      return `<p>${inlineMd(para)}</p>`;
    })
    .join('\n')
    .replace(/<<CODE_BLOCK_(\d+)>>/g, (_, idx) => `<pre><code>${escapeHtml(codeBlocks[Number(idx)] ?? '')}</code></pre>`);

  return html;
}

function inlineMd(text: string): string {
  return text
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/\*([^*]+)\*/g, '<em>$1</em>')
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}
