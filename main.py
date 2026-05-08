from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from api.routes_upload import router as upload_router
from api.routes_agents import router as agents_router
from api.routes_criteria import router as criteria_router
from api.routes_dashboard import router as dashboard_router
from api.routes_calls import router as calls_router
from api.routes_alerts import router as alerts_router
app = FastAPI()
app.include_router(dashboard_router)
app.include_router(upload_router)
app.include_router(agents_router)
app.include_router(criteria_router)
app.include_router(calls_router)
app.include_router(alerts_router)



app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Routes HTML (pages)
@app.get("/upload")
def page_upload(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="upload.html",
        context={"active": "upload"}
    )

@app.get("/dashboard")
def page_dashboard(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={"active": "dashboard"}
    )

@app.get("/calls")
def page_calls(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="calls.html",
        context={"active": "calls"}
    )
# … etc pour les autres pages

@app.get("/rapport")
def page_rapport(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="rapport.html",
        context={"active": "rapport"}
    )



@app.get("/")
def home():
    return {"message": "CallAI running"}


@app.get("/health")
def health():
    return {"status": "ok"}