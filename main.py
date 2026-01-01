# File: main.py

import os
import json
import time
from typing import Dict, List, Optional

from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel

import redis
import requests
from twilio.rest import Client
from twilio.twiml.messaging_response import MessagingResponse

# --------------------------------------------------
# ENV
# --------------------------------------------------
TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_FROM = os.environ.get("TWILIO_WHATSAPP_FROM")
REDIS_URL = os.environ.get("REDIS_URL")

if not REDIS_URL:
    raise RuntimeError("Missing REDIS_URL")

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
    pid: str              # user id
    participant: str      # whatsapp number
    clueyToken: str       # per-user Cluey token


class SendMessage(BaseModel):
    alertId: str
    message: str


# --------------------------------------------------
# REDIS KEYS
# --------------------------------------------------
def redis_messages_key(alert_id: str) -> str:
    return f"alert:{alert_id}:messages"


def redis_user_token_key(pid: str) -> str:
    return f"user:{pid}:cluey_token"


def redis_phone_alert_key(phone: str) -> str:
    return f"phone:{phone}:alert"


# --------------------------------------------------
# MESSAGE STORAGE
# --------------------------------------------------
def store_message(alert_id: str, payload: Dict):
    redis_client.rpush(redis_messages_key(alert_id), json.dumps(payload))


def load_messages(alert_id: str) -> List[Dict]:
    raw = redis_client.lrange(redis_messages_key(alert_id), 0, -1)
    return [json.loads(r) for r in raw]


# --------------------------------------------------
# USER TOKEN STORAGE
# --------------------------------------------------
def store_user_token(pid: str, token: str):
    redis_client.set(redis_user_token_key(pid), token)


def load_user_token(pid: str) -> Optional[str]:
    return redis_client.get(redis_user_token_key(pid))


# --------------------------------------------------
# CLUEY API HELPER (GENERIC)
# --------------------------------------------------
def cluey_request(
    pid: str,
    method: str,
    url: str,
    json_body: Dict | None = None,
):
    token = load_user_token(pid)
    if not token:
        raise HTTPException(status_code=401, detail="No Cluey token for user")

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    resp = requests.request(
        method=method,
        url=url,
        headers=headers,
        json=json_body,
        timeout=15,
    )

    if not resp.ok:
        raise HTTPException(
            status_code=resp.status_code,
            detail=f"Cluey API error: {resp.text}",
        )

    if resp.text:
        return resp.json()
    return None


# --------------------------------------------------
# ENDPOINTS
# --------------------------------------------------
@app.post("/whatsapp/incident/start")
def start_incident(data: StartIncident):
    # store per-user Cluey token
    store_user_token(data.pid, data.clueyToken)

    # bind phone → alert
    redis_client.set(
        redis_phone_alert_key(data.participant),
        data.alertId,
    )

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
            to="whatsapp:+31636037414",  # existing behavior unchanged
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

    alert_id = redis_client.get(redis_phone_alert_key(from_number))
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
