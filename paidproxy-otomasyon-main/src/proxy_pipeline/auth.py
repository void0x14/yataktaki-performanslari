from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Role(StrEnum):
    VIEWER = "viewer"
    OPERATOR = "operator"
    MODE_EDITOR = "mode-editor"
    APPROVER = "approver"
    ADMIN = "admin"


PERMISSIONS = {
    Role.VIEWER: {"read"},
    Role.OPERATOR: {"read", "operate", "feedback"},
    Role.MODE_EDITOR: {"read", "operate", "mode"},
    Role.APPROVER: {"read", "operate", "feedback", "approve"},
    Role.ADMIN: {"read", "operate", "feedback", "mode", "approve", "admin", "kill"},
}


@dataclass(frozen=True)
class Principal:
    name: str
    role: Role
    network: str = "management"


class Authorizer:
    def __init__(self, principals: list[Principal] | None = None) -> None:
        self.principals = {p.name: p for p in principals or [Principal("operator", Role.ADMIN)]}

    def allow(self, name: str, permission: str) -> bool:
        principal = self.principals.get(name)
        if principal is None:
            return False
        return permission in PERMISSIONS[principal.role]

    def require(self, name: str, permission: str) -> Principal:
        if not self.allow(name, permission):
            raise PermissionError(f"{name} lacks {permission}")
        return self.principals[name]
