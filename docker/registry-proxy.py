"""Allowlisting HTTPS proxy for the dependency-install step.

Runs in its own container, attached to an internal Docker network (no route
out) and to the default bridge. The install container is on the internal
network only, so this proxy is its single way out, and it forwards only HTTPS
CONNECT tunnels to the package registry hosts below. Everything else gets 403.
It logs each decision to stdout as one JSON line.

Usage: python registry-proxy.py PORT HOST [HOST ...]
"""

import asyncio
import json
import sys
import time

PORT = int(sys.argv[1])
ALLOWED = {h.lower() for h in sys.argv[2:]}


def log(**kw):
    print(json.dumps({"t": round(time.time(), 3), **kw}), flush=True)


async def pipe(reader, writer):
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    except (ConnectionError, asyncio.CancelledError):
        pass
    finally:
        writer.close()


async def handle(reader, writer):
    try:
        head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 30)
    except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, asyncio.TimeoutError, ConnectionError):
        writer.close()
        return
    line = head.split(b"\r\n", 1)[0].decode("latin-1")
    parts = line.split()
    method, target = (parts + ["", ""])[:2]
    host, _, port = target.rpartition(":")
    host = host.strip("[]").lower()
    if method != "CONNECT" or port != "443" or host not in ALLOWED:
        log(decision="deny", request=line[:200])
        writer.write(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
        await writer.drain()
        writer.close()
        return
    try:
        up_r, up_w = await asyncio.wait_for(asyncio.open_connection(host, 443), 30)
    except (OSError, asyncio.TimeoutError):
        log(decision="error", host=host)
        writer.write(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")
        writer.close()
        return
    log(decision="allow", host=host)
    writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
    await writer.drain()
    await asyncio.gather(pipe(reader, up_w), pipe(up_r, writer))


async def main():
    server = await asyncio.start_server(handle, "0.0.0.0", PORT)
    log(listening=PORT, allowed=sorted(ALLOWED))
    async with server:
        await server.serve_forever()


asyncio.run(main())
