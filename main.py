from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, JSONResponse
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
import os
import requests
from datetime import datetime

app = FastAPI()

# ─────────────────────────────────────────────
# Twilio config (Render env vars)
# ─────────────────────────────────────────────
TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_FROM = os.environ.get("TWILIO_WHATSAPP_FROM")  # whatsapp:+14155238886

client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# ─────────────────────────────────────────────
# Cluey backend config
# ─────────────────────────────────────────────
CLUEY_BASE_URL = os.environ.get("CLUEY_BASE_URL")  # https://cluey.test.sensingclues.org/v1
CLUEY_ACCESS_TOKEN = os.environ.get("CLUEY_ACCESS_TOKEN")

# ─────────────────────────────────────────────
# MVP in-memory state
# incidentId → context
# ─────────────────────────────────────────────
INCIDENTS = {
    # "incident-1": {
    #   "participant": "whatsapp:+31636037414",
    #   "pid": "8633548",
    #   "alertId": "n12b8e8d9c64912ea",
    #   "createdAt": "2026-01-01T12:00:00Z"
    # }
}

# ─────────────────────────────────────────────
# 1. Incident starten (Central → Bridge)
# ─────────────────────────────────────────────
@app.post("/whatsapp/incident/start")
async def start_incident(request: Request):
    data = await request.json()

    incident_id = data.get("incidentId")
    participant = data.get("participant")
    pid = data.get("pid")
    alert_id = data.get("alertId")

    if not incident_id or not participant or not pid or not alert_id:
        return JSONResponse(
            status_code=400,
            content={"error": "Missing incidentId, participant, pid or alertId"}
        )

    INCIDENTS[incident_id] = {
        "participant": participant,
        "pid": pid,
        "alertId": alert_id,
        "createdAt": datetime.utcnow().isoformat()
    }

    return {
        "status": "started",
        "incidentId": incident_id,
        "participant": participant,
        "pid": pid,
        "alertId": alert_id
    }

# ─────────────────────────────────────────────
# 2. Outbound WhatsApp (Central → WhatsApp)
# ─────────────────────────────────────────────
@app.post("/send")
async def send_whatsapp(request: Request):
    """
    Body:
    {
      "incidentId": "incident-1",
      "message": "tekst"
    }
    """
    data = await request.json()

    incident_id = data.get("incidentId")
    message = data.get("message")

    if not incident_id or not message:
        return JSONResponse(
            status_code=400,
            content={"error": "Missing incidentId or message"}
        )

    incident = INCIDENTS.get(incident_id)
    if not incident:
        return JSONResponse(
            status_code=404,
            content={"error": "Unknown incidentId"}
        )

    to = incident["participant"]

    msg = client.messages.create(
        from_=TWILIO_WHATSAPP_FROM,
        to=to,
        body=message
    )

    return {
        "status": "sent",
        "incidentId": incident_id,
        "sid": msg.sid
    }

# ─────────────────────────────────────────────
# 3. Inbound WhatsApp (Twilio → Alert Action)
# ─────────────────────────────────────────────
@app.post("/twilio/webhook")
async def twilio_webhook(request: Request):
    form = await request.form()
    from_number = form.get("From")
    body = form.get("Body")

    # Zoek incident op participant (MVP: 1 actief incident per nummer)
    incident_id = None
    for iid, data in INCIDENTS.items():
        if data["participant"] == from_number:
            incident_id = iid
            break

    if not incident_id:
        resp = MessagingResponse()
        resp.message("Geen actief incident gekoppeld.")
        return PlainTextResponse(str(resp))

    incident = INCIDENTS.get(incident_id)
    pid = incident.get("pid")
    alert_id = incident.get("alertId")

    description = f"[WhatsApp] {from_number}: {body}"

    if CLUEY_BASE_URL and CLUEY_ACCESS_TOKEN and pid and alert_id:
        try:
            url = f"{CLUEY_BASE_URL}/projects/{pid}/alerts/{alert_id}/actions"
            requests.post(
                url,
                headers={
                    "x-access-token": CLUEY_ACCESS_TOKEN,
                    "Content-Type": "application/json"
                },
                json={"description": description},
                timeout=5
            )
        except Exception as e:
            print("FAILED TO POST ALERT ACTION:", str(e))

    print("INBOUND WHATSAPP MESSAGE")
    print({
        "incidentId": incident_id,
        "pid": pid,
        "alertId": alert_id,
        "from": from_number,
        "message": body
    })

    resp = MessagingResponse()
    resp.message("Ontvangen en gekoppeld aan alert.")

    return PlainTextResponse(str(resp))
