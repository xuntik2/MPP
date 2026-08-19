from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import yaml
import os

from .database import engine, Base
from . import models

app = FastAPI(title="МемоСбор")

# Создание таблиц при старте
Base.metadata.create_all(bind=engine)

# Статика и шаблоны
os.makedirs("app/static", exist_ok=True)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

CONFIG_PATH = "config.yaml"

def load_config():
    if not os.path.exists(CONFIG_PATH): return {}
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f) or {}

def save_config(data):
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request, "title": "Дашборд"})

@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, saved: int = 0):
    config = load_config()
    return templates.TemplateResponse("settings.html", {
        "request": request, 
        "config": config, 
        "title": "Настройки API",
        "saved": saved
    })

@app.post("/settings/save")
async def save_settings(
    vk_token: str = Form(""),
    tg_api_id: str = Form("0"),
    tg_api_hash: str = Form(""),
    time_window: int = Form(24)
):
    config = load_config()
    
    # Обновление VK
    if "vk" not in config: config["vk"] = {}
    config["vk"]["service_token"] = vk_token
    
    # Обновление Telegram
    if "telegram" not in config: config["telegram"] = {}
    try:
        config["telegram"]["api_id"] = int(tg_api_id)
    except ValueError:
        config["telegram"]["api_id"] = 0
    config["telegram"]["api_hash"] = tg_api_hash
    
    config["time_window_hours"] = time_window
    
    save_config(config)
    return RedirectResponse(url="/settings?saved=1", status_code=303)