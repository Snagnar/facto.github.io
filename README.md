# Facto Web Compiler

A web-based compiler for the **Facto** programming language, which compiles to Factorio blueprints.

## Overview

This project provides a browser-based IDE for writing and compiling Facto code into Factorio blueprint strings. It features:

- **Real-time syntax highlighting** with CodeMirror
- **Streaming compilation output** via Server-Sent Events (SSE)
- **Example programs** to get started quickly
- **Configurable options** (power poles, blueprint name, optimization, log level)
- **One-click copy** of generated blueprints

## Architecture

```
┌─────────────────────┐        ┌─────────────────────┐
│      Frontend       │  SSE   │       Backend       │
│   (Static Files)    │───────▶│   (FastAPI + Py)    │
│                     │        │                     │
│  - CodeMirror       │        │  - /health (ping)   │
│  - Example loader   │        │  - /connect (stats) │
│  - Compile UI       │        │  - /compile (SSE)   │
└─────────────────────┘        │  - /compile/sync    │
                               └──────────┬──────────┘
                                          │
                                          ▼
                               ┌─────────────────────┐
                               │    factompile       │
                               │  (Facto Compiler)   │
                               └─────────────────────┘
```

## Project Structure

```
facto.github.io/
├── frontend/               # Static web frontend
│   ├── index.html          # Main HTML page
│   ├── css/
│   │   └── style.css       # Factorio-themed styling
│   ├── js/
│   │   ├── app.js          # Main application logic
│   │   ├── compiler.js     # Backend API communication
│   │   └── editor.js       # CodeMirror setup & examples
│   └── assets/             # Images and icons
│
├── backend/                # FastAPI backend server
│   ├── main.py             # FastAPI app & routes
│   ├── compiler_service.py # Compilation logic & queue
│   ├── config.py           # Configuration settings
│   ├── rate_limiter.py     # Rate limiting setup
│   ├── stats.py            # Usage statistics tracking
│   ├── requirements.txt    # Python dependencies
│   └── Dockerfile          # Container build file
│
└── README.md               # This file
```

## Getting Started

### Prerequisites

- Python 3.11+
- `factompile` compiler (`pip install factompile`)

### Running Locally

1. **Install backend dependencies:**
   ```bash
   cd backend
   pip install -r requirements.txt
   ```

2. **Start the backend server:**
   ```bash
   python main.py
   ```
   The server runs at `http://localhost:8000` by default.

3. **Serve the frontend:**
   ```bash
   # From the frontend directory, use any static server:
   cd frontend
   python -m http.server 3000
   ```
   Open `http://localhost:3000` in your browser.

### Configuration

The backend can be configured via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `HOST` | `0.0.0.0` | Server bind address |
| `PORT` | `8000` | Server port |
| `ALLOWED_ORIGINS` | `*` | CORS allowed origins (comma-separated) |
| `FACTO_COMPILER_PATH` | `factompile` | Path to the Facto compiler |
| `COMPILATION_TIMEOUT` | `30` | Max compilation time in seconds |
| `MAX_CONCURRENT_COMPILATIONS` | `1` | Queue ensures single compilation |
| `RATE_LIMIT_REQUESTS` | `10` | Max requests per window |
| `RATE_LIMIT_WINDOW` | `60` | Rate limit window in seconds |

## API Endpoints

### `GET /health`
Simple health check. Returns `{"status": "ok"}`.

### `POST /connect`
Called when frontend connects. Records a session visit for statistics.

Returns:
```json
{
  "connected": true,
  "stats": { ... }
}
```

### `POST /compile`
Compile Facto code with streaming output (SSE).

Request body:
```json
{
  "source": "// Facto code here",
  "power_poles": "medium",      // optional: small|medium|big|substation
  "blueprint_name": "My BP",    // optional
  "no_optimize": false,         // optional
  "json_output": false,         // optional
  "log_level": "info"           // optional: debug|info|warning|error
}
```

SSE events:
- `log` - Compilation log messages
- `status` - Status updates
- `queue` - Queue position updates
- `blueprint` - Final blueprint string (on success)
- `error` - Error messages
- `end` - Compilation complete

### `POST /compile/sync`
Non-streaming compilation endpoint (for clients without SSE support).

## Features

### Compilation Queue
Only one compilation runs at a time. Additional requests are queued with position tracking, allowing users to see their place in line.

### Statistics
Usage statistics are tracked and persisted to `stats.yaml`:
- Unique sessions (visits)
- Total/successful/failed compilations
- Compilation times (avg, median, min, max)

### Rate Limiting
API requests are rate-limited to prevent abuse. Default: 10 requests per 60 seconds.

## Development

### Frontend
The frontend is a static single-page application. Edit files directly and refresh the browser.

Key files:
- [editor.js](frontend/js/editor.js) - CodeMirror configuration and example programs
- [compiler.js](frontend/js/compiler.js) - Backend communication
- [app.js](frontend/js/app.js) - UI logic and event handlers

### Backend
The backend is a FastAPI application.

Key files:
- [main.py](backend/main.py) - Routes and middleware
- [compiler_service.py](backend/compiler_service.py) - Compilation queue and process management
- [stats.py](backend/stats.py) - Statistics collection

## Deployment

### Docker
```bash
cd backend
docker build -t facto-compiler .
docker run -p 8000:8000 facto-compiler
```

### Production Notes
- Set `ALLOWED_ORIGINS` to your frontend domain
- Consider placing behind a reverse proxy (nginx) for SSL
- The `stats.yaml` file should be persisted between container restarts

## License

MIT License - See [LICENSE](LICENSE) for details.
