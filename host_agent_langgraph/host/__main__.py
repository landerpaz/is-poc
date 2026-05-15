import json
import logging
import os
import sys
import uuid
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
import uvicorn
from dotenv import load_dotenv
from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, StreamingResponse
from starlette.routing import Route

from host.agent import HostAgent
from host.auth import login_handler

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_host_agent: HostAgent
_redis: aioredis.Redis

_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Agentic</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f0f4f0; }
    .container { max-width: 820px; margin: 0 auto; padding: 20px; height: 100vh; display: flex; flex-direction: column; gap: 12px; }
    h1 { color: #2c7a2c; font-size: 1.5rem; }
    #messages { flex: 1; border: 1px solid #c8e6c9; border-radius: 10px; background: white; overflow-y: auto; padding: 16px; display: flex; flex-direction: column; gap: 10px; }
    .msg { padding: 10px 14px; border-radius: 8px; max-width: 80%; word-wrap: break-word; white-space: pre-wrap; }
    .user { background: #1976d2; color: white; align-self: flex-end; }
    .agent { background: #e8f5e9; color: #1b5e20; border: 1px solid #c8e6c9; align-self: flex-start; }
    .system { background: #fff8e1; color: #f57f17; font-style: italic; font-size: 0.88em; align-self: flex-start; }
    .label { font-size: 0.72em; opacity: 0.65; margin-bottom: 4px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.03em; }
    #input-row { display: flex; gap: 8px; }
    #user-input { flex: 1; padding: 11px 14px; border: 1px solid #c8e6c9; border-radius: 8px; font-size: 14px; outline: none; background: white; }
    #user-input:focus { border-color: #2c7a2c; box-shadow: 0 0 0 2px rgba(44,122,44,0.15); }
    button { padding: 11px 22px; background: #2c7a2c; color: white; border: none; border-radius: 8px; cursor: pointer; font-size: 14px; font-weight: 600; }
    button:hover { background: #1b5e20; }
    button:disabled { background: #9e9e9e; cursor: not-allowed; }
  </style>
</head>
<body>
  <div class="container">
    <h1>Agentic</h1>
    <div id="messages">
      <div class="msg agent">
        <div class="label">Host Agent</div>
        Hello! How can i help you today?
      </div>
    </div>
    <div id="input-row">
      <input id="user-input" type="text" placeholder="e.g. Update application description" autocomplete="off" />
      <button id="send-btn" onclick="sendMessage()">Send</button>
    </div>
  </div>
  <script>
    const sessionId = Math.random().toString(36).substring(2);
    const messagesEl = document.getElementById('messages');
    const inputEl = document.getElementById('user-input');
    const sendBtn = document.getElementById('send-btn');

    inputEl.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) sendMessage(); });

    function addMsg(role, text, label) {
      const div = document.createElement('div');
      div.className = 'msg ' + role;
      if (label) {
        const lbl = document.createElement('div');
        lbl.className = 'label';
        lbl.textContent = label;
        div.appendChild(lbl);
      }
      const content = document.createElement('div');
      content.textContent = text;
      div.appendChild(content);
      messagesEl.appendChild(div);
      messagesEl.scrollTop = messagesEl.scrollHeight;
      return div;
    }

    async function sendMessage() {
      const text = inputEl.value.trim();
      if (!text || sendBtn.disabled) return;
      inputEl.value = '';
      sendBtn.disabled = true;
      addMsg('user', text, 'You');

      let thinkingEl = addMsg('system', 'The host agent is thinking...', null);

      try {
        const resp = await fetch('/chat', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message: text, session_id: sessionId, chat_id: sessionId })
        });

        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buf = '';

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buf += decoder.decode(value, { stream: true });
          const lines = buf.split('\\n');
          buf = lines.pop();
          for (const line of lines) {
            if (!line.startsWith('data: ')) continue;
            const data = line.slice(6);
            if (data === '[DONE]') break;
            try {
              const chunk = JSON.parse(data);
              if (chunk.is_task_complete) {
                if (thinkingEl) { thinkingEl.remove(); thinkingEl = null; }
                addMsg('agent', chunk.content, 'Host Agent');
              }
            } catch (_) {}
          }
        }
      } finally {
        if (thinkingEl) { thinkingEl.remove(); thinkingEl = null; }
        sendBtn.disabled = false;
        inputEl.focus();
      }
    }
  </script>
</body>
</html>"""


async def homepage(request: Request):
    return HTMLResponse(_HTML)


async def chat_endpoint(request: Request):
    user_id = request.headers.get("X-User-Id", "anonymous")
    body = await request.json()
    query = body.get("message", "")

    # conversation_id format: <user_id>-<uuid>
    # Client sends the same id for every turn of one chat session;
    # a fresh id is created only when the client clicks "Go to Chat".
    conversation_id: str = (
        body.get("conversation_id")
        # or body.get("chat_id")   # backward-compat with legacy HTML client
        # or body.get("session_id")
        or f"conversation:{user_id}:{uuid.uuid4()}"
    )

    # Capture references so the inner generator doesn't rely on mutable outer state
    redis_client = _redis
    conv_id = conversation_id

    await redis_client.rpush(conv_id, json.dumps({"role": "user", "content": query}))
    await redis_client.expire(conv_id, 86400)

    async def generate():
        async for chunk in _host_agent.stream(query, conv_id):
            if chunk.get("is_task_complete") and chunk.get("content"):
                await redis_client.rpush(
                    conv_id,
                    json.dumps({"role": "agent", "content": chunk["content"]}),
                )
                await redis_client.expire(conv_id, 86400)
            yield f"data: {json.dumps(chunk)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@asynccontextmanager
async def lifespan(app: Starlette):
    global _host_agent, _redis
    if not os.getenv("GOOGLE_API_KEY"):
        logger.error("GOOGLE_API_KEY environment variable not set.")
        sys.exit(1)

    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    _redis = aioredis.from_url(redis_url, decode_responses=True)
    logger.info("Redis connected at %s", redis_url)

    domain_agent_urls = ["http://localhost:10005"]
    logger.info("Initializing Host Agent...")
    _host_agent = await HostAgent.create(remote_agent_addresses=domain_agent_urls)
    logger.info("Host Agent ready at http://localhost:10001")
    yield

    await _redis.aclose()


app = Starlette(
    routes=[
        Route("/", homepage),
        Route("/chat", chat_endpoint, methods=["POST"]),
        Route("/auth/login", login_handler, methods=["POST"]),
    ],
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

if __name__ == "__main__":
    uvicorn.run(app, host="localhost", port=10001)
