import os
import json
import time
from typing import Dict, List

from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel

import redis
from twilio.rest import Client
from twilio.twiml.messaging_response import MessagingResponse

# --------------------------------------------------
# ENV
# --------------------------------------------------
TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_FROM = os.environ.get("TWILIO_WHATSAPP_FROM")
CLUEY_ACCESS_TOKEN = os.environ.get("CLUEY_ACCESS_TOKEN")
REDIS_URL = os.environ.get("REDIS_URL")

if not REDIS_URL:
    raise RuntimeError("Missing REDIS_URL")

if not CLUEY_ACCESS_TOKEN:
    raise RuntimeError("Missing CLUEY_ACCESS_TOKEN")

# --------------------------------------------------
# CLIENTS
# --------------------------------------------------
twilio = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

# --------------------------------------------------
# APP
# --------------------------------------------------
app = FastAPI()


# --------------------------------------------------
# MODELS
# --------------------------------------------------
class StartIncident(BaseModel):
    alertId: str
    pid: str
    participant: str


class SendMessage(BaseModel):
    alertId: str
    message: str


# --------------------------------------------------
# HELPERS
# --------------------------------------------------
def redis_key(alert_id: str) -> str:
    return f"alert:{alert_id}:messages"


def store_message(alert_id: str, payload: Dict):
    redis_client.rpush(redis_key(alert_id), json.dumps(payload))


def load_messages(alert_id: str) -> List[Dict]:
    raw = redis_client.lrange(redis_key(alert_id), 0, -1)
    return [json.loads(r) for r in raw]


# --------------------------------------------------
# ENDPOINTS
# --------------------------------------------------
@app.post("/whatsapp/incident/start")
def start_incident(data: StartIncident):
    store_message(
        data.alertId,
        {
            "id": f"sys-{int(time.time())}",
            "direction": "system",
            "text": f"WhatsApp conversation started for alert {data.alertId}",
            "timestamp": int(time.time() * 1000),
        },
    )

    return {
        "status": "started",
        "alertId": data.alertId,
        "participant": data.participant,
    }


@app.post("/send")
def send_message(data: SendMessage):
    try:
        msg = twilio.messages.create(
            from_=TWILIO_WHATSAPP_FROM,
            to="whatsapp:+31636037414",
            body=data.message,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    store_message(
        data.alertId,
        {
            "id": msg.sid,
            "direction": "outbound",
            "text": data.message,
            "timestamp": int(time.time() * 1000),
        },
    )

    return {
        "status": "sent",
        "sid": msg.sid,
        "alertId": data.alertId,
    }


@app.post("/whatsapp/inbound")
async def inbound_whatsapp(request: Request):
    form = await request.form()
    text = form.get("Body")
    from_number = form.get("From")

    alert_id = redis_client.get(f"phone:{from_number}:alert")

    if not alert_id:
        raise HTTPException(status_code=404, detail="No alert bound to this sender")

    store_message(
        alert_id,
        {
            "id": f"in-{int(time.time())}",
            "direction": "inbound",
            "text": text,
            "timestamp": int(time.time() * 1000),
        },
    )

    resp = MessagingResponse()
    return str(resp)


@app.get("/alerts/{alertId}/messages")
def get_messages(alertId: str):
    return load_messages(alertId)
