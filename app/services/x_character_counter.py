import re
import unicodedata
from dataclasses import dataclass

import regex

X_MAX_WEIGHTED_LENGTH = 280
X_RECOMMENDED_LENGTH = 260
X_URL_LENGTH = 23

# DealPilotで使用するAmazonリンクなどを検出します。
URL_PATTERN = re.compile(
    r"https?://[^\s]+",
    flags=re.IGNORECASE,
)

# 絵文字を1つのまとまりとして取得します。
GRAPHEME_PATTERN = regex.compile(r"\X")


@dataclass(frozen=True)
class XTextResult:
    weighted_length: int
    is_valid: bool


def is_single_weight_character(character: str) -> bool:
    """
    Xで1文字として数える範囲を判定します。
    主に半角英数字や一般的な半角記号が対象です。
    """
    code_point = ord(character)

    return (
        0 <= code_point <= 4351
        or 8192 <= code_point <= 8205
        or 8208 <= code_point <= 8223
        or 8242 <= code_point <= 8247
    )


def is_emoji_grapheme(grapheme: str) -> bool:
    """
    絵文字や国旗などを判定します。
    複数の記号で構成された絵文字も、1つのまとまりとして扱います。
    """
    return bool(
        regex.search(
            r"[\p{Extended_Pictographic}\p{Regional_Indicator}]",
            grapheme,
        )
        or "\u20e3" in grapheme
    )


def count_plain_text(text: str) -> int:
    """
    URL以外の文章をXの重み付き文字数で数えます。
    """
    weighted_length = 0

    for grapheme in GRAPHEME_PATTERN.findall(text):
        if is_emoji_grapheme(grapheme):
            weighted_length += 2
            continue

        for character in grapheme:
            # 結合文字は直前の文字に含まれるため追加しません。
            if unicodedata.combining(character):
                continue

            if is_single_weight_character(character):
                weighted_length += 1
            else:
                weighted_length += 2

    return weighted_length


def count_x_characters(text: str) -> XTextResult:
    """
    Xの投稿用文字数を計算します。

    ・半角英数字など：1
    ・日本語など：2
    ・絵文字：基本2
    ・URL：23
    ・改行：1
    """

    # Windowsの改行 \r\n を、通常の改行 \n に統一する
    normalized_line_breaks = (
        text
        .replace("\r\n", "\n")
        .replace("\r", "\n")
    )

    normalized_text = unicodedata.normalize(
        "NFC",
        normalized_line_breaks,
    )

    weighted_length = 0
    current_position = 0

    for match in URL_PATTERN.finditer(normalized_text):
        before_url = normalized_text[
            current_position:match.start()
        ]

        weighted_length += count_plain_text(before_url)
        weighted_length += X_URL_LENGTH

        current_position = match.end()

    remaining_text = normalized_text[current_position:]
    weighted_length += count_plain_text(remaining_text)

    return XTextResult(
        weighted_length=weighted_length,
        is_valid=weighted_length <= X_MAX_WEIGHTED_LENGTH,
    )