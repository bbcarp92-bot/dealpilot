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

from app.database.database import Base, engine, get_database
from app.models.product_candidate import ProductCandidate
from app.sample_products import SAMPLE_PRODUCTS
from app.scoring.product_score import (
    calculate_product_score,
    get_score_label,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="DealPilot",
    version="0.4.0",
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


def create_draft_text(
    product: ProductCandidate,
) -> str:
    prime_text = "Prime対象" if product.is_prime else ""

    details = [
        f"【{product.discount_rate}%OFF】",
        "",
        product.title,
        "",
        (
            f"{product.original_price:,}円"
            f" → {product.current_price:,}円"
        ),
    ]

    if product.rating > 0:
        details.append(
            f"評価 {product.rating}／"
            f"レビュー {product.review_count:,}件"
        )

    if prime_text:
        details.append(prime_text)

    details.extend(
        [
            "",
            "気になる方は商品ページを確認してください。",
            "",
            product.affiliate_url,
            "",
            "#PR #Amazonアソシエイト",
        ]
    )

    return "\n".join(details)


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

    return templates.TemplateResponse(
        request=request,
        name="preview.html",
        context={
            "product": product,
            "saved": saved,
        },
    )


@app.post("/candidates/{candidate_id}/preview")
def save_preview_text(
    candidate_id: int,
    draft_text: str = Form(...),
    database: Session = Depends(get_database),
):
    product = database.get(
        ProductCandidate,
        candidate_id,
    )

    if product is not None:
        product.draft_text = draft_text.strip()
        database.commit()

    return RedirectResponse(
        url=f"/candidates/{candidate_id}/preview?saved=true",
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

    if candidate is not None:
        candidate.status = "approved"
        candidate.decided_at = datetime.now(timezone.utc)
        database.commit()

    return RedirectResponse(
        url="/candidates",
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