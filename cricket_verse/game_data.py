from __future__ import annotations

from dataclasses import dataclass


RUN_CHOICES = (0, 1, 2, 3, 4, 6)
MISS_RUN_WEIGHTS = {0: 15, 1: 25, 2: 30, 3: 20, 4: 15, 6: 10}
CATCH_TIME_WEIGHTS = {120: 30, 150: 50, 180: 20}
CATCH_DROP_RUNS = {120: 1, 150: 2, 180: 3}
HARD_WICKET_TYPES = ("Bowled", "LBW", "Stumped")


@dataclass(frozen=True)
class Delivery:
    code: int
    name: str
    lengths: tuple[str, ...]
    mlr: dict[str, tuple[int, ...]]
    wide_pct: int
    no_ball_pct: int
    leg_bye_pct: int
    spam_wide_pct: int
    spam_no_ball_pct: int
    hard: bool = False
    catch_ball: bool = False
    bouncer: bool = False


PACER_DELIVERIES: dict[int, Delivery] = {
    0: Delivery(
        0,
        "Reverse Swing",
        ("Yorker", "Full"),
        {"Yorker": (0, 1), "Full": (0, 1)},
        4,
        1,
        2,
        75,
        20,
        hard=True,
    ),
    1: Delivery(
        1,
        "Bouncer",
        ("Bouncer", "Short"),
        {"Bouncer": (0, 1, 2), "Short": (0, 1, 2)},
        8,
        6,
        1,
        100,
        60,
        hard=True,
        catch_ball=True,
        bouncer=True,
    ),
    2: Delivery(
        2,
        "Yorker",
        ("Yorker",),
        {"Yorker": (0, 1, 2)},
        5,
        3,
        2,
        90,
        50,
        hard=True,
    ),
    3: Delivery(
        3,
        "Short",
        ("Short",),
        {"Short": (1, 2, 3, 4)},
        6,
        2,
        1,
        80,
        20,
        catch_ball=True,
    ),
    4: Delivery(
        4,
        "Slower",
        ("Full", "Good"),
        {"Full": (1, 2, 4), "Good": (0, 1, 2, 3)},
        4,
        2,
        1,
        65,
        15,
        catch_ball=True,
    ),
    6: Delivery(
        6,
        "Knuckle",
        ("Full", "Yorker"),
        {"Full": (2, 4, 6), "Yorker": (0, 2)},
        3,
        5,
        1,
        50,
        45,
        catch_ball=True,
    ),
}


SPIN_DELIVERIES: dict[int, Delivery] = {
    0: Delivery(
        0,
        "Carrom",
        ("Good",),
        {"Good": (0, 1)},
        3,
        1,
        1,
        60,
        10,
        hard=True,
    ),
    1: Delivery(
        1,
        "Doosra",
        ("Good",),
        {"Good": (0, 1, 2)},
        5,
        1,
        1,
        80,
        15,
        hard=True,
        catch_ball=True,
    ),
    2: Delivery(
        2,
        "Leg Break",
        ("Full", "Good"),
        {"Full": (1, 2, 4), "Good": (1, 2, 3)},
        6,
        1,
        2,
        90,
        10,
        catch_ball=True,
    ),
    3: Delivery(
        3,
        "Top Spin",
        ("Good", "Short"),
        {"Good": (0, 1, 2, 3), "Short": (1, 2, 3, 4)},
        4,
        2,
        1,
        75,
        20,
        hard=True,
        catch_ball=True,
    ),
    4: Delivery(
        4,
        "Flipper",
        ("Full", "Good"),
        {"Full": (2, 4, 6), "Good": (1, 2, 4)},
        5,
        3,
        1,
        70,
        25,
    ),
    6: Delivery(
        6,
        "Googly",
        ("Good", "Full"),
        {"Good": (0, 1, 2), "Full": (2, 4, 6)},
        7,
        2,
        1,
        100,
        15,
        catch_ball=True,
    ),
}


DELIVERIES_BY_STYLE = {
    "pacer": PACER_DELIVERIES,
    "spinner": SPIN_DELIVERIES,
}


def delivery_label(style: str, code: int) -> str:
    delivery = DELIVERIES_BY_STYLE[style][code]
    return f"{code} - {delivery.name}"
