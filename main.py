from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from twilio.twiml.messaging_response import MessagingResponse

app = FastAPI()

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
