from sqlalchemy import Column, Integer, String, DateTime
from app.database import Base
from datetime import datetime

class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String)
    description = Column(String)
    deadline = Column(DateTime)
    status = Column(String, default="pending")
    created_at = Column(DateTime, default=datetime.utcnow)
