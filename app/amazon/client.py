from app.amazon.models import AmazonProduct


class AmazonClient:

    def search_products(
        self,
        keyword: str,
    ) -> list[AmazonProduct]:

        print(f"検索キーワード：{keyword}")

        return [
            AmazonProduct(
                asin="TEST001",
                title="Anker USB-C充電器 65W",

                original_price=5990,
                current_price=3990,

                rating=4.6,
                review_count=3250,

                is_prime=True,

                image_url="",
                product_url="https://amazon.co.jp",

                affiliate_url="https://amzn.to/test",

                category="家電",
            ),

            AmazonProduct(
                asin="TEST002",
                title="Logicool MX Master 3S",

                original_price=16980,
                current_price=12980,

                rating=4.8,
                review_count=8120,

                is_prime=True,

                image_url="",
                product_url="https://amazon.co.jp",

                affiliate_url="https://amzn.to/test",

                category="PC",
            ),
        ]