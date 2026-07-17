from dataclasses import dataclass


@dataclass
class AmazonProduct:
    asin: str
    title: str

    original_price: int
    current_price: int

    rating: float
    review_count: int

    is_prime: bool

    image_url: str
    product_url: str
    affiliate_url: str

    category: str