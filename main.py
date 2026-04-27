from fastapi import FastAPI
from api.routes_upload import router as upload_router

app = FastAPI()

app.include_router(upload_router)


@app.get("/")
def home():
    return {"message": "CallAI running"}


@app.get("/health")
def health():
    return {"status": "ok"}