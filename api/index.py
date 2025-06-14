import os
import json
import logging
from fastapi import FastAPI, Request, Header, HTTPException
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
from linebot import LineBotApi, WebhookParser
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from mangum import Mangum

# Load .env
load_dotenv()

# LINE credentials
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")

if not LINE_CHANNEL_ACCESS_TOKEN or not LINE_CHANNEL_SECRET:
    raise RuntimeError("Missing LINE credentials in environment variables.")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
parser = WebhookParser(LINE_CHANNEL_SECRET)

# Load config.json
try:
    with open("config.json", encoding="utf-8") as f:
        config = json.load(f)
except Exception as e:
    raise RuntimeError("Could not load config.json") from e

default_reply = config.get("default_reply", "内容を理解できませんでした。")
user_states = {}  # user_id: state

# FastAPI app
app = FastAPI()


@app.get("/")
async def health_check():
    return {"status": "ok"}


@app.post("/api/callback")
async def callback(request: Request, x_line_signature: str = Header(None)):
    body = await request.body()
    body_str = body.decode("utf-8")

    try:
        events = parser.parse(body_str, x_line_signature)
    except InvalidSignatureError as e:
        logging.error(f"Invalid signature: {e}")
        raise HTTPException(status_code=400, detail={"error": "Invalid signature"})
    except Exception as e:
        logging.error(f"Parsing error: {e}")
        raise HTTPException(status_code=400, detail={"error": str(e)})

    for event in events:
        if isinstance(event, MessageEvent) and isinstance(event.message, TextMessage):
            user_id = event.source.user_id
            message_text = event.message.text.strip().lower()
            reply_text = handle_message(user_id, message_text)
            # try:
            #     line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
            # except Exception as e:
            #     logging.error(f"LINE reply error: {e}")
            #     raise HTTPException(status_code=500, detail={"error": str(e)})
            if event.reply_token != "dummy-reply-token":  # avoid error during test
                line_bot_api.reply_message(
                    event.reply_token,
                    TextSendMessage(text=reply_text)
                )
            else:
                print(f"[TEST MODE] Reply skipped. Would send: {reply_text}")

    return "OK"


def handle_message(user_id: str, message: str) -> str:
    # Step 1: Ping → Pong
    if message == "ping":
        return "pong"

    # Step 2: Real Estate Inquiry Flow
    state = user_states.get(user_id, "start")

    if message in ["物件", "ぶっけん"]:
        user_states[user_id] = "ask_area"
        return "物件のエリアを教えてください。（例：渋谷区、市川市）"

    elif state == "ask_area":
        user_states[user_id] = "ask_budget"
        return f"「{message}」ですね。ご予算を教えてください。（例：5000万円）"

    elif state == "ask_budget":
        user_states[user_id] = "completed"
        return f"ご予算「{message}」で承りました。ありがとうございます。担当者よりご連絡します。"

    elif state == "completed":
        return "ご質問ありがとうございます。何か他にご用件はございますか？"

    print(" user_states: " , user_states)
    # Step 3: Default Fallback
    return default_reply


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logging.error(f"[Unhandled Error] {exc}")
    return JSONResponse(
        status_code=500,
        content={"error": str(exc)},
    )

handler = Mangum(app)