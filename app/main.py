import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.amazon.search import search_amazon
from app.database.database import Base, engine, get_database
from app.models.product_candidate import ProductCandidate
from app.sample_products import SAMPLE_PRODUCTS
from app.scoring.product_score import (
    calculate_product_score,
    get_score_label,
)
from app.services.x_character_counter import (
    X_MAX_WEIGHTED_LENGTH,
    X_RECOMMENDED_LENGTH,
    count_x_characters,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="DealPilot",
    version="0.5.0",
    lifespan=lifespan,
)

templates = Jinja2Templates(
    directory="app/templates",
)

app.mount(
    "/static",
    StaticFiles(directory="app/static"),
    name="static",
)

SETTINGS_FILE = Path("data/settings.json")

DEFAULT_SETTINGS = {
    "minimum_discount": 30,
    "minimum_price": 1000,
    "maximum_price": 30000,
    "prime_only": True,
    "dry_run": True,
    "search_interval": 30,
}


def load_settings() -> dict:
    if not SETTINGS_FILE.exists():
        save_settings(DEFAULT_SETTINGS)
        return DEFAULT_SETTINGS.copy()

    try:
        with SETTINGS_FILE.open(
            "r",
            encoding="utf-8",
        ) as file:
            saved_settings = json.load(file)
    except (json.JSONDecodeError, OSError):
        return DEFAULT_SETTINGS.copy()

    settings = DEFAULT_SETTINGS.copy()
    settings.update(saved_settings)

    return settings


def save_settings(settings: dict) -> None:
    SETTINGS_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with SETTINGS_FILE.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            settings,
            file,
            ensure_ascii=False,
            indent=2,
        )


def calculate_discount_rate(
    original_price: int,
    current_price: int,
) -> int:
    if original_price <= 0:
        return 0

    if current_price >= original_price:
        return 0

    discount = (
        (original_price - current_price)
        / original_price
        * 100
    )

    return round(discount)


def check_product(
    product: dict,
    settings: dict,
) -> tuple[bool, str]:
    reasons: list[str] = []

    if product["discount_rate"] < settings["minimum_discount"]:
        reasons.append(
            f"割引率が{settings['minimum_discount']}%未満"
        )

    if product["current_price"] < settings["minimum_price"]:
        reasons.append("最低価格より安い")

    if product["current_price"] > settings["maximum_price"]:
        reasons.append("最高価格を超えている")

    if settings["prime_only"] and not product["is_prime"]:
        reasons.append("Prime対象外")

    if reasons:
        return False, "、".join(reasons)

    return True, "設定条件に一致"


def get_x_text_info(text: str) -> tuple[int, bool]:
    result = count_x_characters(text)

    return result.weighted_length, result.is_valid


def create_draft_text(
    product: ProductCandidate,
) -> str:
    product_name = product.title.strip()

    if len(product_name) > 70:
        product_name = product_name[:67] + "..."

    lines = [
        f"【{product.discount_rate}%OFF】",
        product_name,
        "",
        (
            f"{product.original_price:,}円"
            f" → {product.current_price:,}円"
        ),
    ]

    product_details: list[str] = []

    if product.is_prime:
        product_details.append("Prime対象")

    if product.rating > 0:
        product_details.append(f"評価{product.rating}")

    if product_details:
        lines.append("・".join(product_details))

    lines.extend(
        [
            "",
            "▼Amazon",
            product.affiliate_url,
            "",
            "#PR #Amazon",
        ]
    )

    draft_text = "\n".join(lines)

    if len(draft_text) > X_MAX_WEIGHTED_LENGTH:
        short_lines = [
            f"【{product.discount_rate}%OFF】",
            product_name[:45],
            (
                f"{product.original_price:,}円"
                f" → {product.current_price:,}円"
            ),
            product.affiliate_url,
            "#PR #Amazon",
        ]

        draft_text = "\n".join(short_lines)

    return draft_text


@app.get("/", response_class=HTMLResponse)
def home(
    request: Request,
    database: Session = Depends(get_database),
):
    pending_count = database.scalar(
        select(func.count(ProductCandidate.id)).where(
            ProductCandidate.status == "pending"
        )
    ) or 0

    approved_count = database.scalar(
        select(func.count(ProductCandidate.id)).where(
            ProductCandidate.status == "approved"
        )
    ) or 0

    filtered_count = database.scalar(
        select(func.count(ProductCandidate.id)).where(
            ProductCandidate.status == "filtered"
        )
    ) or 0

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "status": "準備完了",
            "search_count": pending_count,
            "post_count": approved_count,
            "filtered_count": filtered_count,
            "settings": load_settings(),
        },
    )


@app.get("/settings", response_class=HTMLResponse)
def settings_page(
    request: Request,
    saved: bool = False,
):
    return templates.TemplateResponse(
        request=request,
        name="settings.html",
        context={
            "settings": load_settings(),
            "saved": saved,
        },
    )


@app.post("/settings")
def update_settings(
    minimum_discount: int = Form(...),
    minimum_price: int = Form(...),
    maximum_price: int = Form(...),
    search_interval: int = Form(...),
    prime_only: bool = Form(False),
    dry_run: bool = Form(False),
):
    settings = {
        "minimum_discount": minimum_discount,
        "minimum_price": minimum_price,
        "maximum_price": maximum_price,
        "prime_only": prime_only,
        "dry_run": dry_run,
        "search_interval": search_interval,
    }

    save_settings(settings)

    return RedirectResponse(
        url="/settings?saved=true",
        status_code=303,
    )


@app.get("/products/new", response_class=HTMLResponse)
def new_product_page(
    request: Request,
    message: str | None = None,
):
    return templates.TemplateResponse(
        request=request,
        name="product_form.html",
        context={
            "message": message,
        },
    )


@app.post("/products/new")
def create_manual_product(
    title: str = Form(...),
    asin: str = Form(...),
    category: str = Form(...),
    original_price: int = Form(...),
    current_price: int = Form(...),
    rating: float = Form(0),
    review_count: int = Form(0),
    product_url: str = Form(""),
    affiliate_url: str = Form(...),
    is_prime: bool = Form(False),
    database: Session = Depends(get_database),
):
    asin = asin.strip().upper()

    discount_rate = calculate_discount_rate(
        original_price,
        current_price,
    )

    score, score_reason = calculate_product_score(
        discount_rate=discount_rate,
        rating=rating,
        review_count=review_count,
        is_prime=is_prime,
        current_price=current_price,
    )

    product = ProductCandidate(
        asin=asin,
        title=title.strip(),
        category=category.strip(),
        original_price=original_price,
        current_price=current_price,
        discount_rate=discount_rate,
        rating=rating,
        review_count=review_count,
        is_prime=is_prime,
        product_url=product_url.strip(),
        affiliate_url=affiliate_url.strip(),
        score=score,
        score_label=get_score_label(score),
        score_reason=score_reason,
        status="pending",
        filter_reason="手動登録",
    )

    product.draft_text = create_draft_text(product)

    database.add(product)

    try:
        database.commit()
        database.refresh(product)
    except IntegrityError:
        database.rollback()

        message = quote(
            "同じASINの商品がすでに登録されています。"
        )

        return RedirectResponse(
            url=f"/products/new?message={message}",
            status_code=303,
        )

    return RedirectResponse(
        url=f"/candidates/{product.id}/preview",
        status_code=303,
    )


@app.get("/candidates", response_class=HTMLResponse)
def candidates_page(
    request: Request,
    message: str | None = None,
    database: Session = Depends(get_database),
):
    candidates = database.scalars(
        select(ProductCandidate)
        .where(ProductCandidate.status == "pending")
        .order_by(
            ProductCandidate.score.desc(),
            ProductCandidate.discount_rate.desc(),
            ProductCandidate.created_at.desc(),
        )
    ).all()

    return templates.TemplateResponse(
        request=request,
        name="candidates.html",
        context={
            "candidates": candidates,
            "message": message,
        },
    )


@app.get(
    "/candidates/{candidate_id}/preview",
    response_class=HTMLResponse,
)
def preview_candidate(
    candidate_id: int,
    request: Request,
    saved: bool = False,
    error: str | None = None,
    database: Session = Depends(get_database),
):
    product = database.get(
        ProductCandidate,
        candidate_id,
    )

    if product is None:
        return RedirectResponse(
            url="/candidates",
            status_code=303,
        )

    if not product.draft_text:
        product.draft_text = create_draft_text(product)
        database.commit()

    character_count, is_valid = get_x_text_info(
        product.draft_text
    )

    error_message = None

    if error == "too-long":
        error_message = (
            "Xの文字数上限を超えています。"
            "文章を短くしてください。"
        )

    return templates.TemplateResponse(
        request=request,
        name="preview.html",
        context={
            "product": product,
            "saved": saved,
            "error_message": error_message,
            "character_count": character_count,
            "is_valid": is_valid,
        },
    )


@app.post("/candidates/{candidate_id}/preview")
def save_preview_text(
    candidate_id: int,
    draft_text: str = Form(...),
    action: str = Form("save"),
    database: Session = Depends(get_database),
):
    product = database.get(
        ProductCandidate,
        candidate_id,
    )

    if product is None:
        return RedirectResponse(
            url="/candidates",
            status_code=303,
        )

    cleaned_text = draft_text.strip()

    _, is_valid = get_x_text_info(cleaned_text)

    if not is_valid:
        return RedirectResponse(
            url=(
                f"/candidates/{candidate_id}/preview"
                "?error=too-long"
            ),
            status_code=303,
        )

    product.draft_text = cleaned_text

    if action == "approve":
        product.status = "approved"
        product.decided_at = datetime.now(timezone.utc)

    database.commit()

    if action == "approve":
        return RedirectResponse(
            url="/history",
            status_code=303,
        )

    return RedirectResponse(
        url=(
            f"/candidates/{candidate_id}/preview"
            "?saved=true"
        ),
        status_code=303,
    )


@app.post("/candidates/sample-batch")
def add_sample_products(
    database: Session = Depends(get_database),
):
    settings = load_settings()

    added_count = 0
    filtered_count = 0
    skipped_count = 0

    for item in SAMPLE_PRODUCTS:
        existing = database.scalar(
            select(ProductCandidate).where(
                ProductCandidate.asin == item["asin"]
            )
        )

        if existing is not None:
            skipped_count += 1
            continue

        accepted, reason = check_product(
            item,
            settings,
        )

        score, score_reason = calculate_product_score(
            discount_rate=item["discount_rate"],
            rating=item["rating"],
            review_count=item["review_count"],
            is_prime=item["is_prime"],
            current_price=item["current_price"],
        )

        product = ProductCandidate(
            asin=item["asin"],
            title=item["title"],
            category=item["category"],
            original_price=item["original_price"],
            current_price=item["current_price"],
            discount_rate=item["discount_rate"],
            rating=item["rating"],
            review_count=item["review_count"],
            is_prime=item["is_prime"],
            product_url="https://www.amazon.co.jp/",
            affiliate_url="https://www.amazon.co.jp/",
            score=score,
            score_label=get_score_label(score),
            score_reason=score_reason,
            status="pending" if accepted else "filtered",
            filter_reason=reason,
        )

        product.draft_text = create_draft_text(product)

        database.add(product)

        if accepted:
            added_count += 1
        else:
            filtered_count += 1

    database.commit()

    message = (
        f"候補{added_count}件、"
        f"除外{filtered_count}件、"
        f"登録済み{skipped_count}件です。"
    )

    return RedirectResponse(
        url=f"/candidates?message={quote(message)}",
        status_code=303,
    )


@app.post("/candidates/reset-test-data")
def reset_test_data(
    database: Session = Depends(get_database),
):
    database.execute(
        delete(ProductCandidate).where(
            ProductCandidate.asin.like("TEST%")
        )
    )

    database.commit()

    message = quote(
        "テスト商品をすべて削除しました。"
    )

    return RedirectResponse(
        url=f"/candidates?message={message}",
        status_code=303,
    )


@app.post("/candidates/{candidate_id}/approve")
def approve_candidate(
    candidate_id: int,
    database: Session = Depends(get_database),
):
    candidate = database.get(
        ProductCandidate,
        candidate_id,
    )

    if candidate is None:
        return RedirectResponse(
            url="/candidates",
            status_code=303,
        )

    _, is_valid = get_x_text_info(
        candidate.draft_text.strip()
    )

    if not is_valid:
        return RedirectResponse(
            url=(
                f"/candidates/{candidate_id}/preview"
                "?error=too-long"
            ),
            status_code=303,
        )

    candidate.status = "approved"
    candidate.decided_at = datetime.now(timezone.utc)

    database.commit()

    return RedirectResponse(
        url="/history",
        status_code=303,
    )


@app.post("/candidates/{candidate_id}/reject")
def reject_candidate(
    candidate_id: int,
    database: Session = Depends(get_database),
):
    candidate = database.get(
        ProductCandidate,
        candidate_id,
    )

    if candidate is not None:
        candidate.status = "rejected"
        candidate.decided_at = datetime.now(timezone.utc)
        database.commit()

    return RedirectResponse(
        url="/candidates",
        status_code=303,
    )


@app.post("/x-character-count")
def x_character_count(
    draft_text: str = Form(""),
):
    character_count, is_valid = get_x_text_info(
        draft_text
    )

    return {
        "character_count": character_count,
        "is_valid": is_valid,
    }


@app.get("/history", response_class=HTMLResponse)
def history_page(
    request: Request,
    database: Session = Depends(get_database),
):
    products = database.scalars(
        select(ProductCandidate)
        .where(ProductCandidate.status != "pending")
        .order_by(ProductCandidate.created_at.desc())
    ).all()

    return templates.TemplateResponse(
        request=request,
        name="history.html",
        context={
            "products": products,
        },
    )


from app.amazon.search import search_amazon
def amazon_search_page(
    request: Request,
):
    return templates.TemplateResponse(
        request=request,
        name="search.html",
        context={
            "products": None,
        },
    )


def amazon_search(
    request: Request,
    keyword: str = Form(...),
):

    products = search_amazon(keyword)

    return templates.TemplateResponse(
        request=request,
        name="search.html",
        context={
            "products": products,
        },
    )


@app.get(
    "/amazon/search",
    response_class=HTMLResponse,
)
def amazon_search_page(
    request: Request,
    message: str | None = None,
):
    return templates.TemplateResponse(
        request=request,
        name="search.html",
        context={
            "products": None,
            "keyword": "",
            "searched": False,
            "message": message,
        },
    )


@app.post(
    "/amazon/search",
    response_class=HTMLResponse,
)
def amazon_search_results(
    request: Request,
    keyword: str = Form(...),
):
    cleaned_keyword = keyword.strip()

    products = search_amazon(
        cleaned_keyword
    )

    return templates.TemplateResponse(
        request=request,
        name="search.html",
        context={
            "products": products,
            "keyword": cleaned_keyword,
            "searched": True,
            "message": None,
        },
    )


@app.post("/amazon/search/add")
def add_search_result_to_candidates(
    asin: str = Form(...),
    title: str = Form(...),
    category: str = Form(...),
    original_price: int = Form(...),
    current_price: int = Form(...),
    rating: float = Form(0),
    review_count: int = Form(0),
    is_prime: bool = Form(False),
    product_url: str = Form(""),
    affiliate_url: str = Form(""),
    database: Session = Depends(get_database),
):
    cleaned_asin = asin.strip().upper()

    existing_product = database.scalar(
        select(ProductCandidate).where(
            ProductCandidate.asin == cleaned_asin
        )
    )

    if existing_product is not None:
        return RedirectResponse(
            url=f"/candidates/{existing_product.id}/preview",
            status_code=303,
    )

    discount_rate = calculate_discount_rate(
        original_price=original_price,
        current_price=current_price,
    )

    score, score_reason = calculate_product_score(
        discount_rate=discount_rate,
        rating=rating,
        review_count=review_count,
        is_prime=is_prime,
        current_price=current_price,
    )

    product = ProductCandidate(
        asin=cleaned_asin,
        title=title.strip(),
        category=category.strip(),
        original_price=original_price,
        current_price=current_price,
        discount_rate=discount_rate,
        rating=rating,
        review_count=review_count,
        is_prime=is_prime,
        product_url=product_url.strip(),
        affiliate_url=affiliate_url.strip(),
        score=score,
        score_label=get_score_label(score),
        score_reason=score_reason,
        status="pending",
        filter_reason="Amazon検索から登録",
    )

    product.draft_text = create_draft_text(
        product
    )

    database.add(product)

    try:
        database.commit()
        database.refresh(product)
    except IntegrityError:
        database.rollback()

        message = quote(
            "商品の登録に失敗しました。"
        )

        return RedirectResponse(
            url=f"/amazon/search?message={message}",
            status_code=303,
        )

    return RedirectResponse(
        url=f"/candidates/{product.id}/preview",
        status_code=303,
    )