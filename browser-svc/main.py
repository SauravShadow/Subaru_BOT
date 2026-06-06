import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

logger = logging.getLogger(__name__)
PROFILE_PATH = Path("/app/browser_profile.json")
CV_DEFAULT_PATH = Path("/app/cv_default.pdf")


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(title="browser-svc", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok", "slots": 5}
