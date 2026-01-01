from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, JSONResponse
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
import os
import requests

app = FastAPI()

# =========================
# Environment variables
# =========================

TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_FROM = os.environ.get("TWILIO_WHATSAPP_FROM")  # e.g. whatsapp:+14155238886

CLUEY_ACCESS_TOKEN = os.environ.get("CLUEY_ACCESS_TOKEN")

if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN or not TWILIO_WHATSAPP_FROM:
    raise RuntimeError("Missing Twilio environment variables")

if not CLUEY_ACCESS_TOKEN:
    raise RuntimeError("Missing CLUEY_ACCESS_TOKEN")

client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# =========================
# In-memory mappings (MVP)
# =========================
# alertId -> {"participant": "...", "pid": "..."}
INCIDENTS = {}

# participant -> alertId
PARTICIPANT_INDEX = {}

# =========================
# Health
# =========================

@app.get("/")
def health():
    return {"status": "ok"}

# =========================
# Start WhatsApp incident
# =========================

@app.post("/whatsapp/incident/start")
async def start_incident(request: Request):
    """
    Body:
    {
      "alertId": "n12b8e8d9c64912ea",
      "pid": "8633548",
      "participant": "whatsapp:+31636037414"
    }
    """
    data = await request.json()

    alert_id = data.get("alertId")
    pid = data.get("pid")
    participant = data.get("participant")

    if not alert_id or not pid or not participant:
        return JSONResponse(
            status_code=400,
            content={"error": "Missing 'alertId', 'pid' or 'participant'"}
        )

    INCIDENTS[alert_id] = {
        "participant": participant,
        "pid": pid
    }
    PARTICIPANT_INDEX[participant] = alert_id

    return JSONResponse(
        content={
            "status": "started",
            "alertId": alert_id,
            "pid": pid,
            "participant": participant
        }
    )

# =========================
# Send WhatsApp message
# =========================

@app.post("/send")
async def send_whatsapp(request: Request):
    """
    Body:
    {
      "alertId": "n12b8e8d9c64912ea",
      "message": "tekst"
    }
    """
    data = await request.json()

    alert_id = data.get("alertId")
    message = data.get("message")

    if not alert_id or not message:
        return JSONResponse(
            status_code=400,
            content={"error": "Missing 'alertId' or 'message'"}
        )

    incident = INCIDENTS.get(alert_id)
    if not incident:
        return JSONResponse(
            status_code=404,
            content={"error": f"No WhatsApp participant for alertId {alert_id}"}
        )

    participant = incident["participant"]

    msg = client.messages.create(
        from_=TWILIO_WHATSAPP_FROM,
        to=participant,
        body=message
    )

    return JSONResponse(
        content={
            "status": "sent",
            "alertId": alert_id,
            "sid": msg.sid
        }
    )

# =========================
# Incoming WhatsApp webhook
# =========================

@app.post("/twilio/webhook")
async def twilio_webhook(request: Request):
    """
    Called by Twilio when a WhatsApp message is received
    """
    form = await request.form()
    from_number = form.get("From")
    body = form.get("Body")

    alert_id = PARTICIPANT_INDEX.get(from_number)
    if not alert_id:
        resp = MessagingResponse()
        resp.message("Geen actief incident gekoppeld aan dit nummer.")
        return PlainTextResponse(str(resp))

    incident = INCIDENTS.get(alert_id)
    pid = incident["pid"]

    url = f"https://cluey.test.sensingclues.org/v1/projects/{pid}/alerts/{alert_id}/actions"

    headers = {
        "x-access-token": CLUEY_ACCESS_TOKEN,
        "Content-Type": "application/json"
    }

    payload = {
        "description": body
    }

    r = requests.post(url, json=payload, headers=headers)

    resp = MessagingResponse()
    if r.status_code == 200:
        resp.message("Ontvangen en toegevoegd aan incident.")
    else:
        resp.message("Fout bij verwerken van bericht.")

    return PlainTextResponse(str(resp))
