import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.database.database import Base, engine, get_database
from app.models.product_candidate import ProductCandidate
from app.sample_products import SAMPLE_PRODUCTS

app = FastAPI(
    title="DealPilot",
    version="0.3.0",
)

templates = Jinja2Templates(directory="app/templates")

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


@app.on_event("startup")
def startup() -> None:
    Base.metadata.create_all(bind=engine)


def load_settings() -> dict:
    if not SETTINGS_FILE.exists():
        save_settings(DEFAULT_SETTINGS)
        return DEFAULT_SETTINGS.copy()

    try:
        with SETTINGS_FILE.open("r", encoding="utf-8") as file:
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

    with SETTINGS_FILE.open("w", encoding="utf-8") as file:
        json.dump(
            settings,
            file,
            ensure_ascii=False,
            indent=2,
        )


def check_product(product: dict, settings: dict) -> tuple[bool, str]:
    reasons = []

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

        accepted, reason = check_product(item, settings)

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
            status="pending" if accepted else "filtered",
            filter_reason=reason,
        )

        database.add(product)

        if accepted:
            added_count += 1
        else:
            filtered_count += 1

    database.commit()

    message = (
        f"候補{added_count}件、除外{filtered_count}件、"
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

    message = quote("テスト商品をすべて削除しました。")

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