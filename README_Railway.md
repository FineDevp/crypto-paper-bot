Quick steps to deploy the feature/react-dashboard branch on Railway

1) Add the project to Railway
- Go to https://railway.app and create or open a project.
- Click "New" -> "Deploy from GitHub" and connect your GitHub account if needed.
- Select repository: FineDevp/crypto-paper-bot, branch: feature/react-dashboard.
- Railway will detect the Dockerfile and build the container.

2) Add environment variables (Project > Variables)
- DASHBOARD_TOKEN = <set-a-secret-token>
- SCAN_INTERVAL = 30   # lower while testing
- START_BALANCE = 50
- PAPER_MODE = 1
- PYTHONUNBUFFERED = 1
- DATABASE_URL = (Railway Postgres connection string, see step 3)

3) Add a Postgres plugin in Railway (optional but recommended)
- In your Railway project, click "Add Plugin" -> Postgres.
- Copy the generated DATABASE_URL and set it in project variables.

4) Deploy & verify
- Click deploy. Watch the build logs.
- Once deployed, open the service URL (Railway assigns it) or check /api/health.
- Use the dashboard at / (open in browser), and use the token you set to log in.

5) Troubleshooting
- If the build fails, open the Build logs and check for missing files or npm errors.
- If the app starts but no trades persist, verify DATABASE_URL is set and reachable.

If you want, I can:
- Merge feature/react-dashboard into main and open a PR.
- Trigger a test deployment (if you grant me permission).