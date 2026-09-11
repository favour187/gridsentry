import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from .db import init_db, SessionLocal
from .routers_api import router, seed

app = FastAPI(title="GridSentry", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(router)

WEB_DIST = os.path.join(os.path.dirname(__file__), "..", "web", "dist")
if os.path.isdir(WEB_DIST):
    app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")


@app.on_event("startup")
def startup():
    init_db()
    db = SessionLocal()
    try:
        seed(db)
    finally:
        db.close()
