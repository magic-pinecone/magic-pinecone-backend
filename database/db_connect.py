from sqlalchemy import create_engine, URL
from sqlalchemy.orm import sessionmaker, declarative_base
from core.config import settings

db_url = URL.create(
    drivername="postgresql+psycopg2",
    username=settings.db_user,
    password=settings.db_password,
    host=settings.db_host,
    port=settings.db_port,
    database=settings.db_name
)

engine = create_engine(
    db_url,
    connect_args={"check_same_thread": False} if "sqlite" == db_url.drivername else {}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
