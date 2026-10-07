"""Holoeye model specifications."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HoloeyeModel:
    name: str
    resolution: tuple[int, int]
    pitch_um: tuple[float, float]
    bitdepth: int = 8


MODELS = {
    "leto": HoloeyeModel("LETO-II", (1920, 1080), (6.4, 6.4)),
    "leto-ii": HoloeyeModel("LETO-II", (1920, 1080), (6.4, 6.4)),
    "leto-2": HoloeyeModel("LETO-II", (1920, 1080), (6.4, 6.4)),
    "pluto": HoloeyeModel("PLUTO-2", (1920, 1080), (8.0, 8.0)),
    "pluto-2": HoloeyeModel("PLUTO-2", (1920, 1080), (8.0, 8.0)),
    "gaea": HoloeyeModel("GAEA-2", (3840, 2160), (3.74, 3.74)),
    "gaea-2": HoloeyeModel("GAEA-2", (3840, 2160), (3.74, 3.74)),
    "luna": HoloeyeModel("LUNA", (1920, 1080), (4.5, 4.5)),
}


def get_model(name: str) -> HoloeyeModel:
    try:
        return MODELS[name.lower()]
    except KeyError as exc:
        raise ValueError(f"Unknown Holoeye model {name!r}. Available: {sorted(MODELS)}") from exc


__all__ = ["HoloeyeModel", "MODELS", "get_model"]
