from fastapi import FastAPI
from api.routes_upload import router as upload_router
from api.routes_agents import router as agents_router
from api.routes_criteria import router as criteria_router
from api.routes_upload import router as upload_router
from api.routes_dashboard import router as dashboard_router
from api.routes_calls import router as calls_router
from api.routes_alerts import router as alerts_router
app = FastAPI()
app.include_router(dashboard_router)
app.include_router(upload_router)
app.include_router(agents_router)
app.include_router(criteria_router)
app.include_router(upload_router)
app.include_router(calls_router)
app.include_router(alerts_router)
@app.get("/")
def home():
    return {"message": "CallAI running"}


@app.get("/health")
def health():
    return {"status": "ok"}