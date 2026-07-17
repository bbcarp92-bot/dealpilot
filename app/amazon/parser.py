from app.amazon.models import AmazonProduct


def parse_product(raw_product):

    return AmazonProduct(
        asin="",
        title="",

        original_price=0,
        current_price=0,

        rating=0,
        review_count=0,

        is_prime=False,

        image_url="",
        product_url="",
        affiliate_url="",

        category="その他",
    )