def calculate_product_score(
    discount_rate: int,
    rating: float,
    review_count: int,
    is_prime: bool,
    current_price: int,
) -> tuple[int, str]:
    score = 0
    reasons: list[str] = []

    # 割引率：最大30点
    if discount_rate >= 50:
        score += 30
        reasons.append("割引率が50%以上")
    elif discount_rate >= 40:
        score += 25
        reasons.append("割引率が40%以上")
    elif discount_rate >= 30:
        score += 20
        reasons.append("割引率が30%以上")
    elif discount_rate >= 20:
        score += 10
        reasons.append("割引率が20%以上")

    # 評価：最大15点
    if rating >= 4.5:
        score += 15
        reasons.append("高評価")
    elif rating >= 4.0:
        score += 10
        reasons.append("評価4.0以上")
    elif rating >= 3.5:
        score += 5

    # レビュー数：最大15点
    if review_count >= 3000:
        score += 15
        reasons.append("レビュー3000件以上")
    elif review_count >= 1000:
        score += 12
        reasons.append("レビュー1000件以上")
    elif review_count >= 300:
        score += 8
        reasons.append("レビュー300件以上")
    elif review_count >= 100:
        score += 4

    # Prime：10点
    if is_prime:
        score += 10
        reasons.append("Prime対象")

    # 購入しやすい価格帯：最大10点
    if 1000 <= current_price <= 5000:
        score += 10
        reasons.append("購入しやすい価格帯")
    elif 5001 <= current_price <= 10000:
        score += 7
    elif 10001 <= current_price <= 30000:
        score += 4

    # 現段階では残り20点分を将来の機能用に残す
    reason_text = "・".join(reasons)

    if not reason_text:
        reason_text = "目立った加点項目なし"

    return min(score, 100), reason_text


def get_score_label(score: int) -> str:
    if score >= 80:
        return "優先候補"

    if score >= 65:
        return "通常候補"

    if score >= 50:
        return "要確認"

    return "低優先"