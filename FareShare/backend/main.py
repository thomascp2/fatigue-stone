from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from database import init_db
from routers import disputes_router

app = FastAPI(
    title="FairShare API",
    description="AI-powered property tax dispute platform for rural Alabama landowners.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(disputes_router)


@app.on_event("startup")
def on_startup():
    settings.ensure_dirs()
    init_db()


@app.get("/health")
def health():
    return {"status": "ok", "version": "0.1.0"}


@app.get("/")
def root():
    return {
        "name": "FairShare API",
        "tagline": "We fight your bills. If we don't save you money, you pay $0.",
        "docs": "/docs",
    }
