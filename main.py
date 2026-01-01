from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, JSONResponse
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
import os
from datetime import datetime

app = FastAPI()

# ─────────────────────────────────────────────
# Twilio config (Render environment variables)
# ─────────────────────────────────────────────
TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_FROM = os.environ.get("TWILIO_WHATSAPP_FROM")  # whatsapp:+14155238886

client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# ─────────────────────────────────────────────
# MVP in-memory state
# incidentId → participant (1 extern nummer)
# ─────────────────────────────────────────────
INCIDENTS = {
    # voorbeeld:
    # "incident-123": {
    #     "participant": "whatsapp:+31636037414",
    #     "createdAt": "2026-01-01T12:00:00Z"
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

    if not incident_id or not participant:
        return JSONResponse(
            status_code=400,
            content={"error": "Missing incidentId or participant"}
        )

    INCIDENTS[incident_id] = {
        "participant": participant,
        "createdAt": datetime.utcnow().isoformat()
    }

    return {
        "status": "started",
        "incidentId": incident_id,
        "participant": participant
    }

# ─────────────────────────────────────────────
# 2. Outbound bericht (Central → WhatsApp)
# ─────────────────────────────────────────────
@app.post("/send")
async def send_whatsapp(request: Request):
    """
    Body:
    {
      "incidentId": "incident-123",
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
# 3. Inbound WhatsApp (Twilio → Bridge)
# ─────────────────────────────────────────────
@app.post("/twilio/webhook")
async def twilio_webhook(request: Request):
    form = await request.form()
    from_number = form.get("From")
    body = form.get("Body")

    # MVP-regel:
    # een extern nummer hoort bij exact 1 actief incident
    incident_id = None
    for iid, data in INCIDENTS.items():
        if data["participant"] == from_number:
            incident_id = iid
            break

    if not incident_id:
        resp = MessagingResponse()
        resp.message("Geen actief incident gekoppeld.")
        return PlainTextResponse(str(resp))

    # Hier zou je dit doorzetten naar het Coordination Center
    print("INBOUND WHATSAPP MESSAGE")
    print("incidentId:", incident_id)
    print("from:", from_number)
    print("body:", body)

    resp = MessagingResponse()
    resp.message("Ontvangen en gekoppeld aan incident.")

    return PlainTextResponse(str(resp))
