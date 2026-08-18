"""The admin menu's shape.

Kept apart from `admin` so the layout can be read and tested without a Telegram client.
Every entry names a config key, so adding a knob to the bot adds it to the menu without
touching the callback plumbing.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Choice:
    label: str
    value: str


@dataclass(frozen=True)
class Setting:
    key: str
    title: str
    choices: tuple[Choice, ...]

    def label_for(self, value: str) -> str:
        for choice in self.choices:
            if choice.value == value:
                return choice.label
        return value


def _numbers(*values: int, suffix: str = "") -> tuple[Choice, ...]:
    return tuple(Choice(f"{v}{suffix}", str(v)) for v in values)


SECTIONS: dict[str, tuple[str, tuple[Setting, ...]]] = {
    "model": (
        "Модель",
        (
            Setting(
                "speak_model",
                "Говорить",
                (
                    Choice("flash-latest", "gemini-flash-latest"),
                    Choice("2.5 flash", "gemini-2.5-flash"),
                    Choice("2.5 lite", "gemini-2.5-flash-lite"),
                ),
            ),
            Setting(
                "digest_model",
                "Денна задача",
                (
                    Choice("2.5 lite", "gemini-2.5-flash-lite"),
                    Choice("2.5 flash", "gemini-2.5-flash"),
                    Choice("flash-latest", "gemini-flash-latest"),
                ),
            ),
            Setting(
                "thinking_budget",
                "Думання",
                (Choice("вимкнене", "0"), Choice("авто", "-1")),
            ),
            Setting(
                "tools_enabled",
                "Пошук і код",
                (Choice("увімкнені", "1"), Choice("вимкнені", "0")),
            ),
        ),
    ),
    "trigger": (
        "Тригер",
        (
            Setting("context_messages", "Контекст", _numbers(30, 60, 100, suffix=" повід.")),
            Setting("throttle_after", "Безкоштовних відповідей", _numbers(3, 6, 12)),
            Setting("throttle_step", "Крок паузи", _numbers(10, 15, 30, suffix=" с")),
            Setting("hourly_reply_cap", "Стеля за годину", _numbers(30, 120, 300)),
            Setting("quiet_from", "Тиша з", _numbers(0, 2, 4, suffix=":00")),
            Setting("quiet_to", "Тиша до", _numbers(6, 8, 10, suffix=":00")),
        ),
    ),
}

MUTE_CHOICES = _numbers(1, 3, 8, suffix=" год")


def cycle(setting: Setting, current: str) -> str:
    """The next value in the ring. One button per setting instead of a submenu each."""
    values = [c.value for c in setting.choices]
    if current not in values:
        return values[0]
    return values[(values.index(current) + 1) % len(values)]
