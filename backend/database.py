from sqlalchemy import create_engine
from urllib.parse import quote_plus
from .config import DATABASE_CONFIG
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

encoded_password = quote_plus(DATABASE_CONFIG['password'])

# 创建数据库连接
engine = create_engine(
    f"mysql+pymysql://{DATABASE_CONFIG['user']}:{encoded_password}@{DATABASE_CONFIG['host']}:3306/{DATABASE_CONFIG['database']}",
    echo=True
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
