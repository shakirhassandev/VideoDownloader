# Video Downloader Plus — Production Build

This build combines the approved static website with a FastAPI backend powered by yt-dlp. Compress / Convert / Trim remain browser-side through ffmpeg.wasm. Download analysis and media downloads run on the backend.

## What is included

- FastAPI API served from the same origin as the website
- yt-dlp media analysis and downloading
- FFmpeg binary supplied by `imageio-ffmpeg` for merging/post-processing
- yt-dlp EJS package through `yt-dlp[default]`
- Automatic detection of installed Deno and Node runtimes
- Format list with video/audio details
- Best-quality and MP3 options
- Download job queue with progress polling
- Temporary-file cleanup
- Maximum duration and file-size limits
- Per-IP in-memory rate limiting
- SSRF protection for obvious private/local/reserved addresses
- No cookies/login import and no DRM bypass
- Docker and Windows startup files

## Run on Windows

Open PowerShell inside this project folder.

### Option A — one command

```powershell
.\start-windows.ps1
```

If PowerShell blocks local scripts, run:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\start-windows.ps1
```

Then open:

```text
http://127.0.0.1:8000
```

### Option B — manual

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

There is no `npm install` step.

## JavaScript runtime for YouTube extraction

Current yt-dlp requires a supported external JavaScript runtime for full YouTube support. Deno is the recommended runtime and is enabled by default by yt-dlp. Node can also be used if it is version 22 or newer.

This project automatically enables Deno and Node when it finds them in `PATH`.

For Windows, install Deno from its official installer, then verify:

```powershell
deno --version
```

Or verify Node 22+:

```powershell
node --version
```

Restart the terminal after installation.

## Docker

```bash
docker compose up --build
```

Open `http://localhost:8000`.

The Docker image installs Deno automatically.

## API

### Analyze media

`POST /api/analyze`

```json
{
  "url": "https://example.com/video-page"
}
```

### Create a download

`POST /api/download`

```json
{
  "url": "https://example.com/video-page",
  "format_id": "best"
}
```

### Job status

`GET /api/jobs/{job_id}`

### Download finished file

`GET /api/jobs/{job_id}/file`

## Production limits

Configure with environment variables. Copy `.env.example` as a reference.

- `MAX_FILE_MB`: maximum media size when known
- `MAX_DURATION_SECONDS`: maximum media duration
- `MAX_CONCURRENT_JOBS`: simultaneous downloader workers
- `JOB_TTL_MINUTES`: temporary-file lifetime
- `INFO_CACHE_MINUTES`: how long an analyzed URL is reused so the download skips a second extraction
- `ANALYZE_RATE_PER_MINUTE`: analysis requests per IP
- `DOWNLOAD_RATE_PER_MINUTE`: download jobs per IP
- `TRUST_PROXY_HEADERS`: enable only behind a trusted reverse proxy

## Important deployment notes

A public downloader is bandwidth-heavy. Shared static hosting is not appropriate for the backend. Use a VPS/container service where Python processes, outbound media traffic and temporary storage are permitted.

The application blocks obvious private/local/reserved destinations before yt-dlp runs, but public arbitrary-URL fetching is still a high-risk service. For serious public deployment, add network-level egress rules so the downloader container cannot reach cloud metadata endpoints, LAN addresses or other internal services even through redirects/DNS rebinding.

Do not add user-supplied cookies, login tokens or DRM-decryption functionality to this public service.

## Before launch

1. Replace `https://example.com` in the website canonicals, robots and sitemap with the real domain.
2. Replace the placeholder support email.
3. Put the backend behind HTTPS and a reverse proxy/CDN.
4. Configure upload/download/bandwidth limits appropriate for the server.
5. Add persistent/rate-limit infrastructure such as Redis if you run multiple application instances.
6. Review legal/publisher-platform requirements for your jurisdiction and intended monetization.
7. Keep yt-dlp and yt-dlp-ejs current because supported sites change frequently.
