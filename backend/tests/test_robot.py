import threading

import pytest
from starlette.websockets import WebSocketDisconnect

from .conftest import TOKEN

HELLO = {"type": "hello", "protocol": 1, "name": "HUMANOID X test sim", "skills": ["gesture", "head_look", "pick_up", "place", "stop"],
         "state": {"estop": False, "holding": {"left": None, "right": None}}}


def test_rejected_when_simulator_absent(client):
    r = client.post("/robot/actions", json={"actions": [{"type": "gesture", "name": "wave"}]})
    assert r.status_code == 503
    rid = r.json()["error"]["request_id"]
    assert client.get(f"/robot/actions/{rid}").json()["status"] == "rejected"


@pytest.mark.parametrize("action", [
    {"type": "head_look", "yaw": 200},                    # beyond joint-safe range: rejected, not clamped
    {"type": "set_joint", "joint": "elbow_R", "value": 3},  # raw joint commands are not a skill
    {"type": "gesture", "name": "wave", "speed": 9},       # unexpected field
    {"type": "speak", "text": "x" * 500},
])
def test_invalid_actions_rejected_and_recorded(client, action):
    r = client.post("/robot/actions", json={"actions": [action]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_action"
    assert client.get(f"/robot/actions/{r.json()['error']['request_id']}").json()["status"] == "rejected"


def test_socket_requires_token(client):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/robot/ws?token=wrong") as ws:
            ws.receive_json()


def test_end_to_end_with_simulator_result(client):
    with client.websocket_connect(f"/robot/ws?token={TOKEN}") as ws:
        ws.send_json(HELLO)
        assert ws.receive_json()["type"] == "welcome"
        assert client.get("/robot/status").json()["connected"] is True
        # skill the simulator didn't offer
        r = client.post("/robot/actions", json={"actions": [{"type": "walk_in_place", "steps": 4}]})
        assert r.status_code == 409
        # place with nothing held
        assert client.post("/robot/actions", json={"actions": [{"type": "place", "target": "green_pad"}]}).status_code == 409
        out = {}
        t = threading.Thread(target=lambda: out.setdefault("r", client.post("/robot/actions", json={
            "actions": [{"type": "pick_up", "object": "red_cube"}, {"type": "place", "target": "green_pad"}], "timeout_s": 10})))
        t.start()
        msg = ws.receive_json()
        assert msg["type"] == "execute" and [a["type"] for a in msg["actions"]] == ["pick_up", "place"]
        ws.send_json({"type": "result", "request_id": msg["request_id"], "status": "completed",
                      "steps": [{"type": "pick_up", "status": "done"}, {"type": "place", "status": "done"}]})
        t.join(10)
        body = out["r"].json()
        assert body["status"] == "completed" and body["result"]["steps"][1]["status"] == "done"


def test_disconnect_never_reports_success(client):
    out = {}
    with client.websocket_connect(f"/robot/ws?token={TOKEN}") as ws:
        ws.send_json(HELLO)
        ws.receive_json()
        t = threading.Thread(target=lambda: out.setdefault("r", client.post("/robot/actions", json={
            "actions": [{"type": "gesture", "name": "wave"}], "timeout_s": 10})))
        t.start()
        ws.receive_json()  # execute arrives, then the simulator vanishes without answering
    t.join(10)
    assert out["r"].json()["status"] == "disconnected"


def test_estop_blocks_motion(client):
    with client.websocket_connect(f"/robot/ws?token={TOKEN}") as ws:
        ws.send_json({**HELLO, "state": {"estop": True, "holding": {}}})
        ws.receive_json()
        r = client.post("/robot/actions", json={"actions": [{"type": "gesture", "name": "wave"}]})
        assert r.status_code == 409 and "Emergency stop" in r.json()["error"]["message"]
        assert client.post("/robot/estop").json()["delivered"] is True
        assert ws.receive_json()["type"] == "estop"
