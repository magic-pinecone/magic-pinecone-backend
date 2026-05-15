from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from routers import test, course, scholarship
from database.db_connect import engine
from database.models import Base
from internal.scheduler import start_scheduler, scheduler
import logging

logging.basicConfig(level=logging.INFO)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    start_scheduler()
    yield
    # Shutdown
    scheduler.shutdown()

app = FastAPI(
    title='Magic Pinecone Backend API',
    description='A project allows NCUers to retrieval the massive campus information in this single platform.',
    version='0.0.0',
    contact={
        'name': 'Shawn Lin',
        'email': 'spig100.roc@gmail.com'
    },
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(test.router)
app.include_router(course.router)
app.include_router(scholarship.router)

@app.get("/")
def root():
    return {"message": "Welcome to Amazing Pinecone Backend!"}