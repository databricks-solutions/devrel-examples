import { createApp, lakebase, server } from '@databricks/appkit';
import { setupCasinoReplayRoutes } from './routes/replay-routes';
import { setupDocsRoutes } from './routes/docs-routes';

createApp({
  plugins: [
    server({ autoStart: false }),
    lakebase(),
  ],
})
  .then(async (appkit) => {
    await setupCasinoReplayRoutes(appkit);
    setupDocsRoutes(appkit);
    await appkit.server.start();
  })
  .catch(console.error);
