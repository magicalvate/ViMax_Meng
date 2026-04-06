import logging

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from frontend.core import STATIC_DIR
from frontend.routers import projects, shots, characters, scripts, pipeline

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="ViMax Preview")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

app.include_router(projects.router)
app.include_router(shots.router)
app.include_router(characters.router)
app.include_router(scripts.router)
app.include_router(pipeline.router)
