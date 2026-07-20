"""Puits SMTP minimal pour les tests E2E de la livraison déclarative.

Aucune dépendance, aucun service externe : parle juste assez de SMTP pour accepter un message et
l'écrire en **JSONL** dans `$SMTP_SINK_FILE` (une ligne par message : from / rcpts / data). Sous
Python 3.13, `smtpd`/`asyncore` ont été retirés → on parle le protocole à la main sur un socket
asyncio. Équivalent local et déterministe d'un « mail catcher » (type Inbucket) pour la CI.
"""
import asyncio
import email
import email.policy
import json
import os

SINK_FILE = os.environ.get("SMTP_SINK_FILE", "smtp-sink.jsonl")
HOST = os.environ.get("SMTP_SINK_HOST", "127.0.0.1")
PORT = int(os.environ.get("SMTP_SINK_PORT", "12525"))


async def _handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    async def send(line: str) -> None:
        writer.write((line + "\r\n").encode())
        await writer.drain()

    await send("220 sink ready")
    mail_from, rcpts = "", []
    try:
        while True:
            raw = await reader.readline()
            if not raw:
                break
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            up = line.upper()
            if up.startswith(("EHLO", "HELO")):
                await send("250 sink")
            elif up.startswith("MAIL FROM"):
                mail_from = line.split(":", 1)[1].strip()
                await send("250 ok")
            elif up.startswith("RCPT TO"):
                rcpts.append(line.split(":", 1)[1].strip())
                await send("250 ok")
            elif up == "DATA":
                await send("354 end with .")
                data_lines = []
                while True:
                    dl = await reader.readline()
                    if not dl or dl.decode("utf-8", "replace").rstrip("\r\n") == ".":
                        break
                    data_lines.append(dl.decode("utf-8", "replace"))
                raw = "".join(data_lines)
                # Corps DÉCODÉ (le quoted-printable des accents est résolu) pour des assertions
                # simples côté test, en plus du MIME brut.
                try:
                    msg = email.message_from_string(raw, policy=email.policy.default)
                    body = msg.get_content()
                    subject = str(msg["Subject"] or "")
                except Exception:  # noqa: BLE001 — le puits ne doit jamais planter
                    body, subject = raw, ""
                with open(SINK_FILE, "a", encoding="utf-8") as f:
                    f.write(json.dumps({"from": mail_from, "rcpts": rcpts, "raw": raw,
                                        "subject": subject, "body": body}) + "\n")
                mail_from, rcpts = "", []
                await send("250 queued")
            elif up == "QUIT":
                await send("221 bye")
                break
            elif up.startswith("RSET"):
                mail_from, rcpts = "", []
                await send("250 ok")
            else:
                await send("250 ok")
    finally:
        writer.close()


async def _main() -> None:
    server = await asyncio.start_server(_handle, HOST, PORT)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(_main())
