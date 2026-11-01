"""Rounding and display helpers shared by the agent scripts."""


def round2(value):
    return round(value + 0.0, 2)


def money(value):
    return "${:,.2f}".format(value)


def pct(value):
    return "{:.2f}%".format(value)


def num(value):
    """Render a number without forcing decimals (keeps the plain text output)."""
    return str(value)
