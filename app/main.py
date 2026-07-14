import json
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

app = FastAPI(title="DealPilot", version="0.1.0")

templates = Jinja2Templates(directory="app/templates")
app.mount("/static", StaticFiles(directory="app/static"), name="static")

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
    """保存済みの設定を読み込みます。"""
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
    """設定をファイルへ保存します。"""
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)

    with SETTINGS_FILE.open("w", encoding="utf-8") as file:
        json.dump(settings, file, ensure_ascii=False, indent=2)


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    settings = load_settings()

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "status": "準備完了",
            "search_count": 0,
            "post_count": 0,
            "settings": settings,
        },
    )


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, saved: bool = False):
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