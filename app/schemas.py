from pydantic import BaseModel
from datetime import datetime

class TaskCreate(BaseModel):
    title: str
    description: str
    deadline: datetime

class TaskResponse(BaseModel):
    id: int
    title: str
    description: str
    deadline: datetime
    status: str

    class Config:
        from_attributes = True
