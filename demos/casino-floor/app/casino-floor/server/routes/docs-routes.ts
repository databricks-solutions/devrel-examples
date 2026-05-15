import { Application } from 'express';
import { readFile, readdir } from 'node:fs/promises';
import { join, resolve } from 'node:path';

interface AppKitWithServer {
  server: {
    extend(fn: (app: Application) => void): void;
  };
}

// Operations corpus lives at demos/casino-floor/data/manuals/. From the
// running server (app/casino-floor/), that's two levels up.
const MANUALS_DIR = resolve(process.cwd(), '..', '..', 'data', 'manuals');

interface ManualSummary {
  slug: string;
  title: string;
  bytes: number;
}

function deriveTitle(slug: string, body: string): string {
  const headingMatch = body.match(/^#\s+(.+)$/m);
  if (headingMatch) return headingMatch[1].trim();
  return slug.replace(/-/g, ' ').replace(/\.md$/, '');
}

export function setupDocsRoutes(appkit: AppKitWithServer) {
  appkit.server.extend((app) => {
    app.get('/api/docs/manuals', async (_req, res) => {
      try {
        const files = await readdir(MANUALS_DIR);
        const summaries: ManualSummary[] = [];
        for (const file of files) {
          if (!file.endsWith('.md')) continue;
          const path = join(MANUALS_DIR, file);
          const body = await readFile(path, 'utf-8');
          summaries.push({
            slug: file.replace(/\.md$/, ''),
            title: deriveTitle(file, body),
            bytes: body.length,
          });
        }
        summaries.sort((a, b) => a.slug.localeCompare(b.slug));
        res.json(summaries);
      } catch (err) {
        console.error('Failed to list manuals:', err);
        res.status(500).json({ error: 'Failed to list manuals' });
      }
    });

    app.get('/api/docs/manuals/:slug', async (req, res) => {
      const slug = req.params.slug;
      if (!/^[A-Za-z0-9-]+$/.test(slug)) {
        res.status(400).json({ error: 'invalid slug' });
        return;
      }
      try {
        const path = join(MANUALS_DIR, `${slug}.md`);
        const body = await readFile(path, 'utf-8');
        res.json({ slug, title: deriveTitle(slug, body), markdown: body });
      } catch (err) {
        if ((err as NodeJS.ErrnoException).code === 'ENOENT') {
          res.status(404).json({ error: 'manual not found' });
          return;
        }
        console.error('Failed to load manual:', err);
        res.status(500).json({ error: 'Failed to load manual' });
      }
    });
  });
}
