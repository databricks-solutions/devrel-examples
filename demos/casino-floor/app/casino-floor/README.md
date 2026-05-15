# casino-floor

A Databricks App powered by [AppKit](https://databricks.github.io/appkit/), featuring React, TypeScript, and Tailwind CSS.

**Enabled plugins:**
- **Lakebase** -- Fully managed Postgres database for transactional (OLTP) workloads on Databricks
- **Server** -- Express HTTP server with static file serving and Vite dev mode

## Prerequisites

- Node.js v22+ and npm
- Databricks CLI (for deployment)
- Access to a Databricks workspace

## Databricks Authentication

### Local Development

For local development, configure your environment variables by creating a `.env` file:

```bash
cp .env.example .env
```

Edit `.env` and set the environment variables you need:

```env
DATABRICKS_HOST=https://your-workspace.cloud.databricks.com
DATABRICKS_APP_PORT=8000
# ... other environment variables, depending on the plugins you use
```

#### Lakebase Configuration

The Lakebase plugin requires additional environment variables for PostgreSQL connectivity. To learn how to configure the Lakebase plugin, see the [Lakebase plugin documentation](https://databricks.github.io/appkit/docs/plugins/lakebase).

### CLI Authentication

The Databricks CLI requires authentication to deploy and manage apps. Configure authentication using one of these methods:

#### OAuth U2M

Interactive browser-based authentication with short-lived tokens:

```bash
databricks auth login --host https://your-workspace.cloud.databricks.com
```

This will open your browser to complete authentication. The CLI saves credentials to `~/.databrickscfg`.

#### Configuration Profiles

Use multiple profiles for different workspaces:

```ini
[DEFAULT]
host = https://dev-workspace.cloud.databricks.com

[production]
host = https://prod-workspace.cloud.databricks.com
client_id = prod-client-id
client_secret = prod-client-secret
```

Deploy using a specific profile:

```bash
databricks bundle deploy --profile production
```

**Note:** Personal Access Tokens (PATs) are legacy authentication. OAuth is strongly recommended for better security.

## Getting Started

### Install Dependencies

```bash
npm install --include=dev
```

> The `.npmrc` sets `production=true` so that the Databricks Apps runtime
> only installs the ~80 production packages at cold-start (the full ~700+
> with build-time devDeps would blow past the 10-minute start cap). For
> local development you need the devDeps (`tsc`, `vite`, `eslint`, etc.),
> so pass `--include=dev`. After the first install, `npm install` works
> as expected because the lockfile is honored.

### Development

Run the app in development mode with hot reload:

```bash
npm run dev
```

The app will be available at the URL shown in the console output.

### Build

Build both client and server for production:

```bash
npm run build
```

This creates:

- `dist/server.js` - Compiled server bundle
- `client/dist/` - Bundled client assets

### Production

Run the production build:

```bash
npm start
```

## Code Quality

There are a few commands to help you with code quality:

```bash
# Type checking
npm run typecheck

# Linting
npm run lint
npm run lint:fix

# Formatting
npm run format
npm run format:fix
```

## Deployment to Databricks Apps

### 1. Configure the bundle

Update `databricks.yml` with your workspace settings:

```yaml
targets:
  default:
    workspace:
      host: https://your-workspace.cloud.databricks.com
```

Make sure to replace placeholder values for the Lakebase branch/database variables with your actual resource IDs.

### 2. Deploy

```bash
databricks apps deploy --profile <your-profile>
```

This runs the AppKit-aware pipeline end-to-end:

1. Validates the project (type-check, lint, build)
2. Builds the frontend + server locally and uploads pre-built artifacts (`dist/`, `client/dist/`)
3. Deploys the bundle and starts the app

> ⚠️ Use `databricks apps deploy`, **not** `databricks bundle deploy`. The latter only uploads source and asks the Databricks Apps runtime to run `npm run build` at start time, which takes longer than the 10-min cold-start window and times out.

### Common flags

- `--target prod` — deploy to a different target
- `--skip-build` — skip the local build step (useful once you've already built)
- `--force-lock` — override a stale deploy lock if a prior deploy hung

### 3. Open the app

```bash
databricks apps get casino-floor --profile <your-profile>
```

The `url` field is the public Databricks Apps URL. Compute may take a few minutes to spin up on first start.

## Project Structure

```
* client/          # React frontend
  * src/           # Source code
  * public/        # Static assets
* server/          # Express backend
  * server.ts      # Server entry point
  * routes/        # Routes
* shared/          # Shared types
* databricks.yml   # Bundle configuration
* app.yaml         # App configuration
* .env.example     # Environment variables example
```

## Tech Stack

- **Backend**: Node.js, Express
- **Frontend**: React.js, TypeScript, Vite, Tailwind CSS, React Router
- **UI Components**: Radix UI, shadcn/ui
- **Databricks**: AppKit SDK
