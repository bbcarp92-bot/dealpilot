from app.amazon.client import AmazonClient


client = AmazonClient()


def search_amazon(
    keyword: str,
):
    return client.search_products(keyword)