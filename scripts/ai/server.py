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
  QWEN_KEY or QWEN_API_KEY, QWEN_MODEL     its key and model
  QWEN_LABEL               name shown in the menu (default "Alibaba Qwen")
  QWEN_REASONING_EFFORT    optional; sent to the model as reasoning_effort (dropped if the model rejects it)
  OPENCODE_API_KEY         OpenCode (opencode.ai Zen) key; with it the OpenCode model appears in the menu (id "opencode")
  OPENCODE_MODEL           its model (default glm-5.3-flash-free)
  OPENCODE_ENDPOINT        OpenAI-compatible base URL (default https://opencode.ai/zen/v1)
  OPENCODE_LABEL           name shown in the menu (default "OpenCode GLM 5.3 Flash")
  OPENCODE2_* ...          more OpenCode models, same names with a number (OPENCODE2_API_KEY, OPENCODE2_MODEL...)
  AI_DEFAULT_PROVIDER      id of the model selected by default (default qwen38, else qwen; "opencode" for OpenCode)
  QWEN37_*, QWEN38_* ...   more Qwen models, same five names with a number in the prefix (QWEN38_ENDPOINT,
                           QWEN38_API_KEY, QWEN38_MODEL, QWEN38_LABEL, QWEN38_REASONING_EFFORT); each one
                           is its own entry in the Model menu. QWEN_* (no number) is the default.
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
MAX_BODY = 6_000_000        # bytes accepted from the browser (screenshots ride along as images)
TIMEOUT = 110               # seconds to wait for the provider
# A provider error is answered with 424, not 502: Cloudflare (in front of the dashboard) replaces any 502 from
# the origin with its own "Bad gateway" page, which hid the provider's actual message from the panel.
PROVIDER_ERR = 424


def env(k):
    return (os.environ.get(k) or "").strip()


def qwen_groups():
    """{id: settings} for every Qwen model set up: QWEN_* (id "qwen") and QWEN<n>_* (id "qwen<n>")."""
    out = {}
    for k in sorted(os.environ):
        m = re.fullmatch(r"(QWEN(\d*))_ENDPOINT", k)
        if not m:
            continue
        pre = m.group(1)
        cfg = {"endpoint": env(pre + "_ENDPOINT").rstrip("/"), "key": env(pre + "_KEY") or env(pre + "_API_KEY"),
               "model": env(pre + "_MODEL"), "label": env(pre + "_LABEL"), "effort": env(pre + "_REASONING_EFFORT")}
        if cfg["endpoint"] and cfg["key"] and cfg["model"]:
            out[pre.lower()] = {**cfg, "label": cfg["label"] or ("Alibaba Qwen" if pre == "QWEN" else "Qwen " + cfg["model"])}
    return out


OPENCODE_ENDPOINT = "https://opencode.ai/zen/v1"
OPENCODE_MODEL = "glm-5.3-flash-free"


def opencode_groups():
    """{id: settings} for every OpenCode model set up: OPENCODE_* (id "opencode") and OPENCODE<n>_* ("opencode<n>").
    Only the key is required; the endpoint and model have defaults."""
    out = {}
    for k in sorted(os.environ):
        m = re.fullmatch(r"(OPENCODE(\d*))_(API_KEY|KEY)", k)
        if not m:
            continue
        pre = m.group(1)
        key = env(pre + "_API_KEY") or env(pre + "_KEY")
        if not key or pre.lower() in out:
            continue
        model = env(pre + "_MODEL") or OPENCODE_MODEL
        out[pre.lower()] = {"endpoint": (env(pre + "_ENDPOINT") or OPENCODE_ENDPOINT).rstrip("/"), "key": key, "model": model,
                            "label": env(pre + "_LABEL") or ("OpenCode GLM 5.3 Flash" if model == OPENCODE_MODEL else "OpenCode " + model),
                            "effort": env(pre + "_REASONING_EFFORT")}
    return out


def providers():
    """The configured providers for the dashboard's Model menu: the default first (Qwen 3.8 Omni Flash, id qwen38), other Qwen models, Azure last."""
    groups = qwen_groups()
    first = env("AI_DEFAULT_PROVIDER") or "qwen38"  # the default model: first in the menu (override with AI_DEFAULT_PROVIDER)
    groups = {**groups, **opencode_groups()}
    out = [{"id": i, "label": groups[i]["label"]} for i in sorted(groups, key=lambda x: (x != first, x != "qwen", x))]
    if env("AZURE_OPENAI_ENDPOINT") and env("AZURE_OPENAI_KEY") and env("AZURE_OPENAI_DEPLOYMENT"):
        out.append({"id": "azure", "label": env("AZURE_OPENAI_LABEL") or "Azure OpenAI"})
    return out


def post(url, headers, body):
    # a named User-Agent: some gateways behind Cloudflare refuse urllib's default one
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json", "User-Agent": "shwapno-ops-dashboard/1", **headers}, method="POST")
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
    """Spoken answers use the default Qwen endpoint and key (QWEN_*); the model and voice have defaults."""
    g = qwen_groups().get("qwen")
    if not g:
        return None
    return {"model": env("QWEN_VOICE_MODEL") or "qwen3.5-omni-flash", "voice": env("QWEN_VOICE") or "Tina", "endpoint": g["endpoint"], "key": g["key"]}


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
    req = urllib.request.Request(cfg["endpoint"] + "/chat/completions", data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": "Bearer " + cfg["key"]})
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
    g = opencode_groups().get(provider)
    if g:
        url, head, base = g["endpoint"] + "/chat/completions", {"Authorization": "Bearer " + g["key"]}, {**body, "model": g["model"]}
        try:
            return post(url, head, base)
        except urllib.error.HTTPError as e:
            # a free model may not take tool calls: answer without the dashboard's lookups rather than fail
            if e.code not in (400, 422) or not tools:
                raise
            plain = {k: v for k, v in base.items() if k not in ("tools", "tool_choice")}
            plain["messages"] = [m for m in base["messages"] if m.get("role") != "tool" and not m.get("tool_calls")]
            return post(url, head, plain)
    g = qwen_groups().get(provider)
    if g:
        url, head, base = g["endpoint"] + "/chat/completions", {"Authorization": "Bearer " + g["key"]}, {**body, "model": g["model"]}
        if g["effort"]:
            try:
                return post(url, head, {**base, "reasoning_effort": g["effort"]})
            except urllib.error.HTTPError as e:
                if e.code != 400:
                    raise  # a 400 may be this model not accepting reasoning_effort: try once without it
        return post(url, head, base)
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
            return self.reply(200, {"enabled": bool(cfg), **({"model": cfg["model"], "voice": cfg["voice"]} if cfg else {})})
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
            self.reply(PROVIDER_ERR, {"error": f"The AI service answered {e.code}. {detail}".strip()})
        except urllib.error.URLError as e:
            self.reply(PROVIDER_ERR, {"error": f"Could not reach the AI service ({e.reason})."})
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
        self.reply(PROVIDER_ERR, {"error": f"The voice service answered {e.code}. {detail}".strip()})
    except urllib.error.URLError as e:
        self.reply(PROVIDER_ERR, {"error": f"Could not reach the voice service ({e.reason})."})
    except Exception as e:  # noqa: BLE001
        self.reply(500, {"error": f"Reading the answer aloud failed ({type(e).__name__}: {e})."})


Handler.do_speak = _speak_handler


if __name__ == "__main__":
    print(f"Shwapno Intelligence relay on 127.0.0.1:{PORT}; providers: {', '.join(p['label'] for p in providers()) or 'none configured'}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
