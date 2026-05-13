from dataclasses import dataclass


@dataclass(frozen=True)
class DomainWarning:
    code: str
    message: str
    field: str | None = None
