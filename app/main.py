from fastapi import FastAPI
from app.api.webhooks import router as webhooks_router

app = FastAPI(title="Tattoo Booking Bot")


@app.get("/health")
def health():
    return {"ok": True}


app.include_router(webhooks_router, prefix="/webhooks")
