from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
import os

app = FastAPI(title="2048 Game", version="1.0.0")

# Serve static files (the game UI)
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def root():
    return FileResponse("static/index.html")

@app.get("/health")
async def health():
    return JSONResponse({"status": "healthy", "service": "2048-game"})

@app.get("/ready")
async def ready():
    return JSONResponse({"status": "ready", "service": "2048-game"})

@app.get("/info")
async def info():
    return JSONResponse({
        "service": "2048-game",
        "version": os.getenv("APP_VERSION", "unknown"),
        "environment": os.getenv("APP_ENV", "unknown")
    })