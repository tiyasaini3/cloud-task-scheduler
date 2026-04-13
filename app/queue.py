import pika
import json
import os
from dotenv import load_dotenv

load_dotenv()

RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")

def send_task(task_id, deadline):
    connection = pika.BlockingConnection(
        pika.ConnectionParameters(host=RABBITMQ_HOST)
    )
    channel = connection.channel()
    channel.queue_declare(queue='tasks')

    message = json.dumps({
        "task_id": task_id,
        "deadline": deadline.isoformat()
    })

    channel.basic_publish(exchange='', routing_key='tasks', body=message)
    connection.close()
