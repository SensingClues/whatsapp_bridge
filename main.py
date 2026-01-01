from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, JSONResponse
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
import os

app = FastAPI()

# Twilio credentials via environment variables (Render)
TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_FROM = os.environ.get("TWILIO_WHATSAPP_FROM")  # e.g. whatsapp:+14155238886

client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)


@app.post("/twilio/webhook")
async def twilio_webhook(request: Request):
    form = await request.form()
    from_number = form.get("From")
    body = form.get("Body")

    print("INCOMING WHATSAPP MESSAGE")
    print("From:", from_number)
    print("Body:", body)

    resp = MessagingResponse()
    resp.message(f"Ontvangen: {body}")

    return PlainTextResponse(str(resp))


@app.post("/send")
async def send_whatsapp(request: Request):
    """
    Body:
    {
      "to": "whatsapp:+316xxxxxxxx",
      "message": "tekst"
    }
    """
    data = await request.json()

    to = data.get("to")
    message = data.get("message")

    if not to or not message:
        return JSONResponse(
            status_code=400,
            content={"error": "Missing 'to' or 'message'"}
        )

    msg = client.messages.create(
        from_=TWILIO_WHATSAPP_FROM,
        to=to,
        body=message
    )

    return JSONResponse(
        content={
            "status": "sent",
            "sid": msg.sid
        }
    )
