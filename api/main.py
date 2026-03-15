"""FastAPI application for SpanNILM."""

import os

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

from api.routers import analysis, circuits, dashboard, profile

app = FastAPI(title="SpanNILM", description="Device detection from SPAN circuit power data")

cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(analysis.router)
app.include_router(circuits.router)
app.include_router(dashboard.router)
app.include_router(profile.router)


@app.get("/health")
def health():
    return {"status": "ok"}
