"""FastAPI application for the Facto web compiler."""

import json
import logging
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse, Response
from pydantic import BaseModel, Field
from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import BaseHTTPMiddleware

from config import get_settings
from rate_limiter import limiter, rate_limit_exceeded_handler
from compiler_service import (
    compile_facto,
    CompilerOptions,
    OutputType,
)
from stats import get_stats

settings = get_settings()
logger = logging.getLogger("facto_backend")


# ==================== Security Middleware ====================


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses."""

    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)

        # Prevent clickjacking
        response.headers["X-Frame-Options"] = "DENY"

        # Prevent MIME type sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"

        # XSS protection (legacy but still useful for older browsers)
        response.headers["X-XSS-Protection"] = "1; mode=block"

        # Referrer policy
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Permissions policy - disable unnecessary browser features
        response.headers["Permissions-Policy"] = (
            "geolocation=(), microphone=(), camera=()"
        )

        return response


# ==================== Application Setup ====================

# Create FastAPI app
app = FastAPI(
    title="Facto Web Compiler",
    description="Web API for compiling Facto code to Factorio blueprints",
    version="1.0.0",
    # Disable API docs in production if debug_mode is False
    docs_url="/docs" if settings.debug_mode else None,
    redoc_url="/redoc" if settings.debug_mode else None,
)

# Add security headers middleware
app.add_middleware(SecurityHeadersMiddleware)

# Add rate limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

# Configure CORS
if settings.allowed_origins == "*":
    origins = ["*"]
else:
    origins = [origin.strip() for origin in settings.allowed_origins.split(",")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
    max_age=86400,  # Cache preflight for 24 hours
)


# ==================== Request Models ====================


class CompileRequest(BaseModel):
    """Request body for compilation."""

    source: str = Field(..., max_length=50000, description="Facto source code")
    power_poles: str | None = Field(None, pattern="^(small|medium|big|substation)$")
    blueprint_name: str | None = Field(None, max_length=100)
    no_optimize: bool = False
    json_output: bool = False
    log_level: str = Field("info", pattern="^(debug|info|warning|error)$")


# ==================== Routes ====================


@app.get("/health")
async def health_check():
    """Simple health check endpoint - just confirms the backend is alive."""
    return {"status": "ok"}


@app.post("/connect")
async def connect():
    """
    Called when frontend connects. Records a unique session visit.
    Returns stats for admin/debugging purposes.
    """
    stats = get_stats()
    await stats.record_session()
    return {"connected": True, "stats": stats.get_stats()}


@app.post("/compile")
@limiter.limit(f"{settings.rate_limit_requests}/{settings.rate_limit_window}seconds")
async def compile_code(request: Request, body: CompileRequest):
    """
    Compile Facto code and stream the output.

    Returns a Server-Sent Events stream with compilation progress and results.
    """
    client_ip = request.client.host if request.client else "unknown"
    logger.info(
        f"Compilation request from {client_ip}, source length: {len(body.source)}"
    )

    options = CompilerOptions(
        power_poles=body.power_poles,
        name=body.blueprint_name,
        no_optimize=body.no_optimize,
        json_output=body.json_output,
        log_level=body.log_level,
    )

    async def event_generator():
        """Generate SSE events from compiler output."""
        try:
            async for output_type, content in compile_facto(body.source, options):
                # Format as SSE
                event_data = json.dumps({"type": output_type.value, "content": content})
                yield f"data: {event_data}\n\n"

            # Send end event
            yield f"data: {json.dumps({'type': 'end', 'content': ''})}\n\n"
        except Exception as e:
            logger.error(f"Error during compilation streaming: {e}", exc_info=True)
            error_data = json.dumps({"type": "error", "content": str(e)})
            yield f"data: {error_data}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


@app.post("/compile/sync")
@limiter.limit(f"{settings.rate_limit_requests}/{settings.rate_limit_window}seconds")
async def compile_code_sync(request: Request, body: CompileRequest):
    """
    Compile Facto code and return all results at once.

    Alternative to streaming for clients that don't support SSE.
    """
    client_ip = request.client.host if request.client else "unknown"
    logger.info(f"Sync compilation request from {client_ip}")

    options = CompilerOptions(
        power_poles=body.power_poles,
        name=body.blueprint_name,
        no_optimize=body.no_optimize,
        json_output=body.json_output,
        log_level=body.log_level,
    )

    logs = []
    blueprint = None
    json_output = None
    errors = []
    status = None

    try:
        async for output_type, content in compile_facto(body.source, options):
            if output_type == OutputType.LOG:
                logs.append(content)
            elif output_type == OutputType.BLUEPRINT:
                blueprint = content
            elif output_type == OutputType.JSON:
                json_output = content
            elif output_type == OutputType.ERROR:
                errors.append(content)
            elif output_type == OutputType.STATUS:
                status = content
    except Exception as e:
        logger.error(f"Error during sync compilation: {e}", exc_info=True)
        errors.append(str(e))

    return {
        "success": blueprint is not None,
        "status": status,
        "logs": logs,
        "blueprint": blueprint,
        "json": json_output,
        "errors": errors,
    }


# ==================== Stats Server ====================

# Create a separate minimal app for serving stats
stats_app = FastAPI(
    title="Facto Stats Server",
    description="Internal stats endpoint",
    docs_url=None,
    redoc_url=None,
)


@stats_app.get("/stats")
async def get_stats_endpoint():
    """Return current statistics."""
    stats = get_stats()
    return stats.get_stats()


@stats_app.get("/health")
async def stats_health_check():
    """Health check for stats server."""
    return {"status": "ok", "service": "stats"}


if __name__ == "__main__":
    import uvicorn
    import threading

    # Start stats server in a separate thread
    def run_stats_server():
        uvicorn.run(
            stats_app,
            host=settings.host,
            port=settings.stats_port,
            log_level="warning",
        )

    stats_thread = threading.Thread(target=run_stats_server, daemon=True)
    stats_thread.start()
    logger.info(f"Stats server starting on {settings.host}:{settings.stats_port}")

    # Run main server on main thread
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        log_level="info",
    )
