#!/usr/bin/env python3
"""Shwapno Intelligence (SI) relay, the dashboard's Ask AI chat: forwards the dashboard's chat requests to Azure OpenAI or Qwen, holding the keys.

The browser runs the conversation and every data lookup itself (with the dashboard's own data and rules),
so this service only adds the provider's address and key and passes the chat request through. Keys come
from environment variables (set them in Coolify), never from the repository or the browser.

  GET  /api/ai/providers   [{"id": "azure", "label": "Azure OpenAI"}, ...] for the providers configured
  POST /api/ai/chat        {"provider": "azure", "messages": [...], "tools": [...]}
                           -> {"message": {...}} (the provider's reply) or {"error": "..."}
  GET  /api/ai/voice       {"enabled": true, "voice": "Tina", "model": "..."} when spoken answers are set up
  POST /api/ai/speak       {"text": "..."} -> audio/wav: the answer read aloud by a Qwen omni model
                           (English; it cannot speak Bangla, so Bangla text is translated as it is read)

Environment:
  AZURE_OPENAI_ENDPOINT    the Azure AI / OpenAI endpoint (a project URL or a resource URL)
  AZURE_OPENAI_KEY         its key
  AZURE_OPENAI_DEPLOYMENT  the model deployment name
  AZURE_OPENAI_LABEL       name shown in the menu (default "Azure OpenAI")
  QWEN_ENDPOINT            OpenAI-compatible base URL (ends with /compatible-mode/v1)
  QWEN_KEY, QWEN_MODEL     its key and model
  QWEN_LABEL               name shown in the menu (default "Alibaba Qwen")
  QWEN_VOICE_MODEL         model that reads answers aloud through Chat Completions with audio output
                           (default qwen3.5-omni-flash; a "-realtime" model cannot be used here, it takes
                           only live audio over a WebSocket)
  QWEN_VOICE               its voice (default Tina); spoken answers use QWEN_ENDPOINT and QWEN_KEY
  AI_PORT                  port on 127.0.0.1 (default 8090); nginx proxies /api/ai/ to it
Usage: python scripts/ai/server.py
"""
import base64
import json
import os
import re
import struct
import sys
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("AI_PORT") or 8090)
MAX_BODY = 600_000          # bytes accepted from the browser
TIMEOUT = 110               # seconds to wait for the provider


def env(k):
    return (os.environ.get(k) or "").strip()


def providers():
    """The configured providers, Qwen first: it is the default in the dashboard's Model menu."""
    out = []
    if env("QWEN_ENDPOINT") and env("QWEN_KEY") and env("QWEN_MODEL"):
        out.append({"id": "qwen", "label": env("QWEN_LABEL") or "Alibaba Qwen"})
    if env("AZURE_OPENAI_ENDPOINT") and env("AZURE_OPENAI_KEY") and env("AZURE_OPENAI_DEPLOYMENT"):
        out.append({"id": "azure", "label": env("AZURE_OPENAI_LABEL") or "Azure OpenAI"})
    return out


def post(url, headers, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json", **headers}, method="POST")
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))


def azure_urls():
    """Chat-completions URLs to try, newest API first. A project URL (…services.ai.azure.com/api/projects/x)
    and a resource URL (…openai.azure.com) both reach the OpenAI-compatible routes on the same host."""
    ep = env("AZURE_OPENAI_ENDPOINT").rstrip("/")
    host = urllib.parse.urlsplit(ep if "://" in ep else "https://" + ep)
    base = f"{host.scheme}://{host.netloc}"
    dep = urllib.parse.quote(env("AZURE_OPENAI_DEPLOYMENT"))
    return [(f"{base}/openai/v1/chat/completions", True),
            (f"{base}/openai/deployments/{dep}/chat/completions?api-version=2024-10-21", False)]


def voice_cfg():
    """Spoken answers need the Qwen endpoint and key; the model and voice have defaults."""
    if not (env("QWEN_ENDPOINT") and env("QWEN_KEY")):
        return None
    return {"model": env("QWEN_VOICE_MODEL") or "qwen3.5-omni-flash", "voice": env("QWEN_VOICE") or "Tina"}


SPEAK_PROMPT = ("You are the voice of a retail operations dashboard. Read the user's text aloud in clear, natural English. "
                "If it is in Bangla, say its meaning in English. Say only that text: no greeting, no comments, no questions. "
                "Read ৳ as taka, Lac as lakh, Cr as crore, and % as percent.")


def wav(pcm, rate=24000):
    """Raw 16-bit mono PCM -> a WAV file (a provider that already sent a WAV header is passed through)."""
    if pcm[:4] == b"RIFF":
        return pcm
    return b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16) + b"data" + struct.pack("<I", len(pcm)) + pcm


def speak(text):
    """Stream the reading from the Qwen omni model and return (wav bytes, spoken transcript)."""
    cfg = voice_cfg()
    body = {"model": cfg["model"], "stream": True, "modalities": ["text", "audio"], "audio": {"voice": cfg["voice"], "format": "wav"},
            "messages": [{"role": "system", "content": SPEAK_PROMPT}, {"role": "user", "content": text}]}
    req = urllib.request.Request(env("QWEN_ENDPOINT").rstrip("/") + "/chat/completions", data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": "Bearer " + env("QWEN_KEY")})
    parts, said = [], []
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        for raw in r:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:") or line == "data: [DONE]":
                continue
            try:
                ch = (json.loads(line[5:]).get("choices") or [{}])[0].get("delta") or {}
            except ValueError:
                continue
            au = ch.get("audio") or {}
            if au.get("data"):
                parts.append(base64.b64decode(au["data"]))
            if au.get("transcript"):
                said.append(au["transcript"])
    if not parts:
        raise ValueError("no audio in the reply")
    return wav(b"".join(parts)), "".join(said)


def chat(provider, messages, tools):
    body = {"messages": messages}
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    if provider == "azure":
        last = None
        for url, with_model in azure_urls():
            try:
                return post(url, {"api-key": env("AZURE_OPENAI_KEY")}, {**body, **({"model": env("AZURE_OPENAI_DEPLOYMENT")} if with_model else {})})
            except urllib.error.HTTPError as e:
                last = e
                if e.code not in (404, 400):  # a different route will not help
                    raise
        raise last
    if provider == "qwen":
        url = env("QWEN_ENDPOINT").rstrip("/") + "/chat/completions"
        return post(url, {"Authorization": "Bearer " + env("QWEN_KEY")}, {**body, "model": env("QWEN_MODEL")})
    raise ValueError("unknown provider")


class Handler(BaseHTTPRequestHandler):
    server_version = "ops-ai/1"

    def log_message(self, fmt, *args):  # quiet: no request bodies or keys in the logs
        sys.stderr.write("ai: %s %s\n" % (self.command, self.path.split("?")[0]))

    def reply(self, code, obj):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.split("?")[0] == "/api/ai/providers":
            return self.reply(200, providers())
        if self.path.split("?")[0] == "/api/ai/voice":
            cfg = voice_cfg()
            return self.reply(200, {"enabled": bool(cfg), **(cfg or {})})
        self.reply(404, {"error": "not found"})

    def do_POST(self):
        if self.path.split("?")[0] == "/api/ai/speak":
            return self.do_speak()
        if self.path.split("?")[0] != "/api/ai/chat":
            return self.reply(404, {"error": "not found"})
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0 or n > MAX_BODY:
            return self.reply(413, {"error": "The question and its data are too large."})
        try:
            req = json.loads(self.rfile.read(n).decode("utf-8"))
            pid = req.get("provider")
            if pid not in {p["id"] for p in providers()}:
                return self.reply(400, {"error": "That AI is not set up on the server."})
            res = chat(pid, req.get("messages") or [], req.get("tools") or [])
            msg = ((res.get("choices") or [{}])[0]).get("message") or {}
            self.reply(200, {"message": msg, "model": res.get("model"), "usage": res.get("usage")})
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = json.loads(e.read().decode("utf-8")).get("error", {}).get("message", "")
            except Exception:  # noqa: BLE001
                pass
            self.reply(502, {"error": f"The AI service answered {e.code}. {detail}".strip()})
        except urllib.error.URLError as e:
            self.reply(502, {"error": f"Could not reach the AI service ({e.reason})."})
        except Exception as e:  # noqa: BLE001
            self.reply(500, {"error": f"Shwapno Intelligence failed ({type(e).__name__})."})


def _speak_handler(self):
    if not voice_cfg():
        return self.reply(400, {"error": "Spoken answers are not set up (QWEN_ENDPOINT and QWEN_KEY)."})
    n = int(self.headers.get("Content-Length") or 0)
    if n <= 0 or n > 20_000:
        return self.reply(413, {"error": "That answer is too long to read aloud."})
    try:
        text = str(json.loads(self.rfile.read(n).decode("utf-8")).get("text") or "")
        text = re.sub(r"[*_`#|>]+", " ", text)[:1500].strip()  # no markdown symbols read aloud
        if not text:
            return self.reply(400, {"error": "Nothing to read."})
        audio, said = speak(text)
        self.send_response(200)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Spoken", urllib.parse.quote(said[:900]))
        self.send_header("Content-Length", str(len(audio)))
        self.end_headers()
        self.wfile.write(audio)
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = json.loads(e.read().decode("utf-8")).get("error", {}).get("message", "")
        except Exception:  # noqa: BLE001
            pass
        self.reply(502, {"error": f"The voice service answered {e.code}. {detail}".strip()})
    except urllib.error.URLError as e:
        self.reply(502, {"error": f"Could not reach the voice service ({e.reason})."})
    except Exception as e:  # noqa: BLE001
        self.reply(500, {"error": f"Reading the answer aloud failed ({type(e).__name__}: {e})."})


Handler.do_speak = _speak_handler


if __name__ == "__main__":
    print(f"Shwapno Intelligence relay on 127.0.0.1:{PORT}; providers: {', '.join(p['label'] for p in providers()) or 'none configured'}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
