# МемоСбор — Парсер мемов с веб-интерфейсом

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109-green.svg)](https://fastapi.tiangolo.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Локальный парсер русскоязычных мемов с удобным веб-интерфейсом для модерации, автоматическим сжатием изображений и отправкой подборок на почту.

## 🚀 Возможности

- **Автоматический сбор** мемов из VK, Telegram, Pikabu, JoyReactor, 2ch
- **Веб-интерфейс** для модерации (одобрить/отклонить) с горячими клавишами
- **Умное сжатие** изображений до ≤150 КБ с сохранением качества
- **Планировщик задач** (запуск по расписанию)
- **Отправка подборок** на email в виде HTML-письма
- **Защита от дублей** (perceptual hash)
- **Гибкая настройка** порогов популярности и категорий

## 📋 Требования

- Python 3.11 или выше
- Windows (для `start.bat`) / Linux / macOS
- Доступ в интернет

## 🛠️ Быстрый старт

### 1. Установка

```bash
# Клонируйте репозиторий
git clone <URL_ВАШЕГО_РЕПОЗИТОРИЯ>
cd memesbor

# Создайте виртуальное окружение и установите зависимости
python -m venv venv
venv\Scripts\activate  # Для Windows
# source venv/bin/activate  # Для Linux/Mac

pip install -r requirements.txt
```

### 2. Настройка (config.yaml)

Откройте файл `config.yaml` и заполните ключи API:

```yaml
vk:
  service_token: "ВАШ_КЛЮЧ_VK"  # https://vk.com/dev
telegram:
  api_id: 123456                # https://my.telegram.org
  api_hash: "ВАШ_HASH"
mail:
  enabled: true
  smtp_host: "smtp.yandex.ru"
  login: "ваша@почта.ru"
  password: "пароль_приложения"
  recipients: ["куда@отправлять.ru"]
```

> **Важно:** Для Telegram потребуется одноразовый ввод кода из SMS при первом запуске.

### 3. Запуск

#### Вариант А: Через start.bat (Windows)
Просто дважды кликните на файл `start.bat`. Он сам создаст окружение, установит зависимости и откроет браузер.

#### Вариант Б: Вручную
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```
Затем откройте в браузере: `http://localhost:8000`

## 📂 Структура проекта

```
memesbor/
├── app/
│   ├── main.py              # Точка входа FastAPI
│   ├── database.py          # Подключение к SQLite
│   ├── models.py            # Модели БД (Meme, RunLog)
│   ├── config_loader.py     # Загрузка config.yaml
│   ├── parsers/             # Парсеры источников
│   │   ├── base.py
│   │   ├── vk_parser.py
│   │   ├── telegram_parser.py
│   │   └── ...
│   ├── services/            # Бизнес-логика
│   │   ├── collector.py     # Сбор и фильтрация
│   │   ├── compressor.py    # Сжатие изображений
│   │   ├── mailer.py        # Отправка почты
│   │   └── scheduler.py     # Планировщик
│   ├── templates/           # HTML шаблоны
│   └── static/              # CSS/JS
├── data/                    # БД и файлы мемов
├── tests/                   # Unit-тесты
├── config.yaml              # Конфигурация
├── requirements.txt
└── start.bat
```

## 🎮 Использование

### Модерация
1. Откройте `http://localhost:8000`
2. Просматривайте новые мемы в галерее
3. Используйте кнопки **Одобрить** / **Отклонить** или горячие клавиши:
   - `→` / `Enter` — одобрить
   - `←` / `Backspace` — отклонить

### Сжатие и отправка
1. Перейдите на вкладку **"Одобренные"**
2. Нажмите **"Сжать все"** для оптимизации изображений
3. Нажмите **"Отправить на почту"** для рассылки подборки

### Настройка расписания
В разделе **"Настройки"** укажите время запуска парсера (например, `09:00`, `14:00`, `19:00`).

## 🧪 Тестирование

Запуск unit-тестов:
```bash
pytest tests/ -v
```

Запуск с покрытием:
```bash
pytest tests/ --cov=app --cov-report=html
```

## 🔑 Получение API ключей

### VK API
1. Зайдите на https://vk.com/dev
2. Создайте приложение типа "Service"
3. Скопируйте **Service Token** в `config.yaml`

### Telegram API
1. Зайдите на https://my.telegram.org/apps
2. Создайте новое приложение
3. Скопируйте **API ID** и **API Hash** в `config.yaml`

### Почта (Yandex/Gmail)
1. Включите двухфакторную аутентификацию
2. Создайте **"Пароль приложения"** в настройках безопасности
3. Используйте его в поле `password`

## ⚙️ Конфигурация

| Параметр | Описание | Пример |
|---|---|---|
| `time_window_hours` | Собирать мемы за последние N часов | `24` |
| `thresholds.vk` | Мин. лайков для VK | `200` |
| `compress.target_kb` | Целевой размер файла | `150` |
| `schedule` | Время запуска | `["09:00", "19:00"]` |

## 🐛 Решение проблем

- **Ошибка "Module not found"**: Убедитесь, что активировано venv и установлены зависимости.
- **Telegram не подключается**: Проверьте `api_id` и `api_hash`. При первом запуске введите код из SMS в консоль.
- **Письма не приходят**: Проверьте лог `data/app.log`. Для Gmail/Yandex используйте "Пароль приложения", а не основной пароль.

## 📄 Лицензия

MIT License. См. файл [LICENSE](LICENSE).

---
**МемоСбор © 2024** | Сделано с ❤️ для любителей юмора
