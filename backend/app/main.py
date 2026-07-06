import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import query, status
from app.auth import load_idp_metadata, saml_acs, saml_metadata
from app.db.models import Base
from app.db.session import engine
from app.services.annotation import load_annotation

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

app = FastAPI(title="Gene Coverage App")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://your-frontend-domain.example.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    log.info("Loading annotation files...")
    load_annotation()
    log.info("Fetching IdP SAML metadata...")
    await load_idp_metadata()
    log.info("Startup complete.")


@app.get("/saml/metadata")
async def metadata(request: Request):
    return await saml_metadata(request)


@app.post("/saml/acs")
async def acs(request: Request):
    return await saml_acs(request)


app.include_router(query.router, prefix="/api")
app.include_router(status.router, prefix="/api")


@app.get("/healthz")
async def health():
    return {"status": "ok"}
