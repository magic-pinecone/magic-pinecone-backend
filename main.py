from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import os

from routers import test, course, scholarship
from database.db_connect import engine
from database.models import Base
from internal.scheduler import start_scheduler, scheduler
import logging

logging.basicConfig(level=logging.INFO)

# Load Server URLs for API Documentation testing (Swagger UI)
gateway_url = os.getenv("GATEWAY_URL", "http://localhost:18080")
backend_url = os.getenv("BACKEND_URL", "http://localhost:8000")

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
    lifespan=lifespan,
    servers=[
        {"url": gateway_url, "description": "API Gateway (DigiRunner)"},
        {"url": backend_url, "description": "Direct Backend (Restricted)"}
    ]
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
