from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session
from app.database import SessionLocal, engine, Base
from app import models, schemas
from app.queue import send_task

app = FastAPI()

Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.post("/tasks", response_model=schemas.TaskResponse)
def create_task(task: schemas.TaskCreate, db: Session = Depends(get_db)):
    new_task = models.Task(
        title=task.title,
        description=task.description,
        deadline=task.deadline
    )
    db.add(new_task)
    db.commit()
    db.refresh(new_task)

    send_task(new_task.id, new_task.deadline)

    return new_task

@app.get("/tasks")
def get_tasks(db: Session = Depends(get_db)):
    return db.query(models.Task).all()

@app.put("/tasks/{task_id}/complete")
def complete_task(task_id: int, db: Session = Depends(get_db)):
    task = db.query(models.Task).filter(models.Task.id == task_id).first()
    task.status = "completed"
    db.commit()
    return {"message": "Task completed"}

@app.delete("/tasks/{task_id}")
def delete_task(task_id: int, db: Session = Depends(get_db)):
    task = db.query(models.Task).filter(models.Task.id == task_id).first()
    db.delete(task)
    db.commit()
    return {"message": "Task deleted"}
