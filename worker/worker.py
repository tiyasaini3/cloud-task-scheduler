import pika
import json
import time
from datetime import datetime
import redis

r = redis.Redis(host="redis", port=6379)

def callback(ch, method, properties, body):
    data = json.loads(body)
    task_id = data["task_id"]
    deadline = datetime.fromisoformat(data["deadline"])

    r.set(f"task:{task_id}", "pending")

    wait_time = (deadline - datetime.utcnow()).total_seconds()

    if wait_time > 0:
        time.sleep(wait_time)

    print(f"Reminder: Task {task_id} is due!")

    r.set(f"task:{task_id}", "completed")

    with open("logs/logs.txt", "a") as f:
        f.write(f"Task {task_id} executed at {datetime.utcnow()}\n")

connection = pika.BlockingConnection(
    pika.ConnectionParameters(host="rabbitmq")
)
channel = connection.channel()
channel.queue_declare(queue='tasks')

channel.basic_consume(queue='tasks', on_message_callback=callback, auto_ack=True)

print("Worker started...")
channel.start_consuming()
