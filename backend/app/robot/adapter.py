"""WebSocket hub for the HUMANOID X simulator. The simulator, not the model, reports what actually happened."""
from __future__ import annotations

import asyncio
import contextlib
import logging

log = logging.getLogger("hc.robot")
PROTOCOL = 1


class SimulatorHub:
    def __init__(self) -> None:
        self.ws = None
        self.hello: dict | None = None
        self.state: dict = {}
        self.pending: dict[str, asyncio.Future] = {}

    @property
    def connected(self) -> bool:
        return self.ws is not None and self.hello is not None

    async def attach(self, ws) -> None:
        if self.ws is not None:
            with contextlib.suppress(Exception):
                await self.ws.close(code=4000)
            self.detach()
        self.ws = ws

    def detach(self) -> None:
        for fut in self.pending.values():
            if not fut.done():
                fut.set_result({"status": "disconnected", "detail": "Simulator disconnected before reporting a result."})
        self.pending.clear()
        self.ws, self.hello, self.state = None, None, {}

    async def handle(self, msg: dict) -> None:
        t = msg.get("type")
        if t == "hello":
            if msg.get("protocol") != PROTOCOL:
                await self.ws.send_json({"type": "error", "detail": f"Unsupported protocol {msg.get('protocol')}; expected {PROTOCOL}."})
                return
            self.hello, self.state = msg, msg.get("state") or {}
            await self.ws.send_json({"type": "welcome", "protocol": PROTOCOL})
            log.info("simulator connected with %d skills", len(msg.get("skills") or []))
        elif t == "state":
            self.state = msg.get("state") or {}
        elif t == "result":
            fut = self.pending.pop(str(msg.get("request_id")), None)
            if fut and not fut.done():
                if isinstance(msg.get("state"), dict):
                    self.state = msg["state"]
                status = msg.get("status")
                fut.set_result({"status": status if status in ("completed", "failed", "cancelled") else "failed",
                                "detail": str(msg.get("detail") or "")[:500], "steps": msg.get("steps") or []})

    async def execute(self, request_id: str, actions: list[dict], timeout: float) -> dict:
        if not self.connected:
            return {"status": "disconnected", "detail": "Simulator is not connected."}
        fut = asyncio.get_running_loop().create_future()
        self.pending[request_id] = fut
        await self.ws.send_json({"type": "execute", "request_id": request_id, "actions": actions})
        try:
            return await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            self.pending.pop(request_id, None)
            return {"status": "timeout", "detail": f"No result from the simulator within {timeout:.0f} s."}

    async def estop(self) -> bool:
        if self.ws is None:
            return False
        await self.ws.send_json({"type": "estop"})
        return True

    async def close(self) -> None:
        if self.ws is not None:
            with contextlib.suppress(Exception):
                await self.ws.close()
        self.detach()
