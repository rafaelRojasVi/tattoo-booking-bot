from fastapi import FastAPI
from app.api.webhooks import router as webhooks_router
from app.api.admin import router as admin_router
from app.api.actions import router as actions_router

app = FastAPI(title="Tattoo Booking Bot")


@app.get("/health")
def health():
    return {"ok": True}


app.include_router(webhooks_router, prefix="/webhooks")
app.include_router(admin_router, prefix="/admin", tags=["admin"])
app.include_router(actions_router, tags=["actions"])