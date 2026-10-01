"""Strict schema for actions HUMANOID X may perform. Out-of-range values are rejected, not clamped."""
from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

Obj = Literal["red_cube", "blue_cylinder", "far_sphere"]
Pad = Literal["green_pad", "amber_pad"]
Side = Literal["left", "right", "both"]
Gesture = Literal["wave", "raise_hand", "point", "think", "nod", "shake_head", "bow", "shrug", "celebrate", "look_around", "curious_tilt"]
Expr = Literal["neutral", "happy", "curious", "surprised", "thinking", "concerned", "focused", "error"]


class _A(BaseModel):
    model_config = ConfigDict(extra="forbid")
    wait: bool = True


class HeadLook(_A):
    type: Literal["head_look"]
    yaw: float = Field(0, ge=-80, le=80)
    pitch: float = Field(0, ge=-35, le=35)
    hold_ms: int = Field(900, ge=0, le=6000)


class LookAt(_A):
    type: Literal["look_at"]
    target: Literal["camera", "red_cube", "blue_cylinder", "far_sphere", "green_pad", "amber_pad"]
    hold_ms: int = Field(1400, ge=0, le=6000)


class Recenter(_A):
    type: Literal["recenter_head"]


class GestureA(_A):
    type: Literal["gesture"]
    name: Gesture
    side: Side = "right"


class ExpressionA(_A):
    type: Literal["expression"]
    name: Expr
    duration_ms: int = Field(3000, ge=300, le=10000)


class Speak(_A):
    type: Literal["speak"]
    text: str = Field(min_length=1, max_length=240)


class HandPose(_A):
    type: Literal["hand_pose"]
    side: Side = "right"
    pose: Literal["open", "relaxed", "close", "pinch", "point"]


class Walk(_A):
    type: Literal["walk_in_place"]
    steps: int = Field(8, ge=2, le=24)


class PickUp(_A):
    type: Literal["pick_up"]
    object: Obj


class Place(_A):
    type: Literal["place"]
    target: Pad


class Reach(_A):
    type: Literal["reach"]
    object: Obj


class Wait(_A):
    type: Literal["wait"]
    ms: int = Field(600, ge=0, le=8000)


class ResetPose(_A):
    type: Literal["reset_pose"]


class Stop(_A):
    type: Literal["stop"]


RobotAction = Annotated[Union[HeadLook, LookAt, Recenter, GestureA, ExpressionA, Speak, HandPose, Walk, PickUp, Place, Reach,
                              Wait, ResetPose, Stop], Field(discriminator="type")]
SKILLS = ["head_look", "look_at", "recenter_head", "gesture", "expression", "speak", "hand_pose", "walk_in_place",
          "pick_up", "place", "reach", "wait", "reset_pose", "stop"]


class ActionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    actions: list[RobotAction] = Field(min_length=1, max_length=10)
    conversation_id: str | None = None
    wait: bool = True
    timeout_s: float = Field(60, ge=1, le=300)


def preconditions(plan: ActionPlan, hello: dict | None, state: dict) -> str | None:
    """Return a rejection reason, or None if the plan may be sent."""
    if hello is None:
        return "The simulator is not connected."
    offered = set(hello.get("skills") or [])
    for a in plan.actions:
        if a.type not in offered:
            return f"The simulator does not offer the '{a.type}' skill."
    if state.get("estop") and any(a.type != "stop" for a in plan.actions):
        return "Emergency stop is active. Resume in the simulator first."
    holding = any((state.get("holding") or {}).values())
    for a in plan.actions:
        if a.type == "pick_up":
            holding = True
        if a.type == "place" and not holding:
            return "Nothing is held, so there is nothing to place."
        if a.type == "place":
            holding = False
    return None
