"""Cell-level normalisation: number parsing, labels, join keys and column coercion."""

from __future__ import annotations

import datetime as dt
import math
import re

import pandas as pd

_BN_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")
ERROR_TOKENS = {"#n/a", "#na", "#div/0!", "#value!", "#ref!", "#name?", "#num!", "#null!"}
BLANK_TOKENS = {"-", "--", "—", "–", "n/a", "na", "nil", "none", "null"} | ERROR_TOKENS
_NUMBER = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$")
_CURRENCY = re.compile(r"^(৳|tk\.?|bdt|rs\.?|\$)\s*", re.I)
_TOTAL_LABEL = re.compile(r"^(.{0,40}\s)?(grand\s*total|sub[\s-]*total|total|মোট|সর্বমোট)\s*:?$", re.I)

_TOTAL_PREFIX = re.compile(r"^((grand\s*|sub[\s-]*)?total\b|মোট|সর্বমোট)", re.I)


def is_missing(value) -> bool:
    if value is None or value is pd.NaT:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    return isinstance(value, str) and not value.strip()


def parse_number(value) -> float | None:
    """Read 1,234.50 / (1,234) / 1,234.00- / 12% / ৳500 / ১২৩ as a number, else None."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(value) else None
    if not isinstance(value, str):
        return None
    text = value.strip().translate(_BN_DIGITS)
    if not text:
        return None
    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative, text = True, text[1:-1].strip()
    text = _CURRENCY.sub("", text)
    if len(text) > 1 and text.endswith("-"):
        negative, text = not negative, text[:-1].strip()
    percent = text.endswith("%")
    if percent:
        text = text[:-1].strip()
    text = text.replace(",", "").replace(" ", "")
    if not _NUMBER.match(text):
        return None
    number = float(text)
    if percent:
        number /= 100
    return -number if negative else number


def identifier_like(value) -> bool:
    """Codes such as 00123 or a 16+ digit number must stay text or they get damaged."""
    if not isinstance(value, str):
        return False
    text = value.strip().translate(_BN_DIGITS)
    return bool(re.fullmatch(r"0\d+", text) or re.fullmatch(r"\d{16,}", text))


def is_total_label(value) -> bool:
    return isinstance(value, str) and bool(_TOTAL_LABEL.match(value.strip()))


def total_label_in_row(row: list) -> str | None:
    """Find a totals row. 'Total Foods' next to an outlet code is a name, not a total."""
    for index, cell in enumerate(row[:5]):
        if not isinstance(cell, str):
            continue
        text = cell.strip()
        if is_total_label(text):
            return text
        if _TOTAL_PREFIX.match(text):
            other_text = any(isinstance(c, str) and c is not cell and c.strip() for c in row)
            blank_before = index > 0 and all(c is None for c in row[:index])
            if text.endswith(":") or (blank_before and not other_text):
                return text
    return None


def norm_label(value) -> str:
    """Match labels regardless of case, spacing or punctuation."""
    text = str(value).translate(_BN_DIGITS).casefold()
    return re.sub(r"[\W_]+", "", text)


def key_norm(value) -> str:
    """Join key form, so ' d051 ', 'D051', 1001, 1001.0 and '1001.0' line up."""
    if is_missing(value):
        return ""
    if isinstance(value, bool):
        return str(value).casefold()
    if isinstance(value, (int,)):
        return str(value)
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else repr(value)
    if isinstance(value, (dt.datetime, dt.date, pd.Timestamp)):
        return value.isoformat()[:10]
    text = re.sub(r"\s+", " ", str(value).translate(_BN_DIGITS)).strip().casefold()
    if re.fullmatch(r"[1-9]\d*\.0+", text):
        return text.split(".")[0]
    return text


def as_text(value):
    if is_missing(value):
        return None
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else repr(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()[:10]
    if isinstance(value, (dt.datetime, dt.date)):
        return value.isoformat()[:10]
    return str(value).strip()


def numeric(series: pd.Series) -> pd.Series:
    """Numeric view of a column; anything unreadable becomes NaN."""
    if pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series):
        return series
    if pd.api.types.is_datetime64_any_dtype(series):
        return pd.Series(float("nan"), index=series.index)
    parsed = [parse_number(v) for v in series.to_numpy(dtype=object)]
    return pd.Series(parsed, index=series.index, dtype="float64")


def coerce_column(series: pd.Series) -> tuple[pd.Series, dict]:
    """Give a column its real type without ever damaging codes or hiding bad cells."""
    info: dict = {"errors": 0, "non_numeric": []}
    values = [v for v in series.to_numpy(dtype=object) if not is_missing(v)]
    if not values:
        return series, info
    kinds = {type(v) for v in values}
    if kinds <= {int, float}:
        return pd.to_numeric(series, errors="coerce"), info
    if kinds <= {dt.date, dt.datetime, pd.Timestamp}:
        return pd.to_datetime(series, errors="coerce"), info

    strings = [v for v in values if isinstance(v, str)]
    info["errors"] = sum(1 for v in strings if v.strip().casefold() in ERROR_TOKENS)
    if any(identifier_like(v) for v in strings):
        return series.map(as_text).astype(object), info

    numbers = blanks = 0
    bad: list[str] = []
    for value in values:
        if parse_number(value) is not None:
            numbers += 1
        elif isinstance(value, str) and value.strip().casefold() in BLANK_TOKENS:
            blanks += 1
        else:
            bad.append(str(value))
    if numbers and numbers + blanks == len(values):
        return numeric(series), info
    if numbers >= 0.8 * len(values):
        info["non_numeric"] = sorted(set(bad))[:5]
    return series, info
