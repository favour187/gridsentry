from app.main import app

@app.on_event('startup')
def _ensure_db():
    from app.db import init_db
    from app.db import SessionLocal
    from app.routers_api import seed
    init_db()
    db = SessionLocal()
    try:
        seed(db)
    finally:
        db.close()
