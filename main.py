import asyncio
import aiohttp
import re
import logging
import os
from collections import defaultdict
from functools import lru_cache
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineQueryResultArticle, InputTextMessageContent
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

API_TOKEN = os.getenv('BOT_TOKEN')
if not API_TOKEN:
    raise ValueError("BOT_TOKEN не найден в .env файле")

bot = Bot(token=API_TOKEN)
dp = Dispatcher()

@lru_cache(maxsize=100)
async def get_repo_info(repo_url: str):
    """Асинхронное получение информации о репозитории с кэшированием"""
    try:
        # Валидация URL
        if not is_valid_github_url(repo_url):
            return None, None, None

        parts = repo_url.strip("/").split("/")
        owner, repo = parts[3], parts[4].replace(".git", "")

        async with aiohttp.ClientSession() as session:
            # Получение основной информации
            repo_info_url = f"https://api.github.com/repos/{owner}/{repo}"
            async with session.get(repo_info_url) as response:
                if response.status != 200:
                    return None, None, None
                info = await response.json()

            if "message" in info:
                return None, None, None

            # Извлечение данных
            description = info.get("description", "нет описания") or "нет описания"
            stars = info.get("stargazers_count", 0)
            language = info.get("language", "не указан")
            default_branch = info.get("default_branch", "main")
            forks_count = info.get("forks_count", 0)
            issues_count = info.get("open_issues_count", 0)
            updated_at = info.get("updated_at", "")

            # Форматирование информации
            repo_info = (
                f"<b>📦 Репозиторий: <a href='https://github.com/{owner}'>{owner}</a>/<a href='https://github.com/{owner}/{repo}'>{repo}</a></b>\n"
                f"⭐ <b>Звёзды:</b> <code>{stars}</code>\n"
                f"💻 <b>Язык:</b> <code>{language}</code>\n"
                f"🍴 <b>Форки:</b> <code>{forks_count}</code>\n"
                f"🚨 <b>Issues:</b> <code>{issues_count}</code>\n"
                f"📝 <b>Описание:</b> <code>{description}</code>\n"
            )

            # Получение структуры файлов
            tree_url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/{default_branch}?recursive=1"
            async with session.get(tree_url) as response:
                if response.status == 200:
                    tree_data = await response.json()
                    files = [item["path"] for item in tree_data.get("tree", []) if item["type"] == "blob"]
                    tree_text = build_tree(files, limit=50)
                    if len(files) > 50:
                        tree_text += f"\n...и ещё {len(files) - 50} файлов"
                else:
                    tree_text = "Не удалось получить структуру файлов"

            # Получение README
            readme_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{default_branch}/README.md"
            async with session.get(readme_url) as response:
                if response.status == 200:
                    readme_text = await response.text()
                    readme_text = clean_readme_text(readme_text)
                    if len(readme_text) > 1000:
                        readme_text = readme_text[:1000] + "\n... (обрезано)"
                else:
                    readme_text = "README.md не найден"

            return repo_info, tree_text, readme_text

    except Exception as e:
        logger.error(f"Ошибка при получении информации о репозитории: {e}")
        return None, None, None

def is_valid_github_url(url: str) -> bool:
    """Проверка валидности GitHub URL"""
    return url.startswith(("http://github.com/", "https://github.com/")) and len(url.split("/")) >= 5

def clean_readme_text(text: str) -> str:
    """Очистка README от неподдерживаемых тегов и форматирования"""
    text = re.sub(r'<img[^>]*>', '', text)
    text = re.sub(r'!\[.*?\]\(.*?\)', '', text)
    text = text.replace('<', '&lt;').replace('>', '&gt;')
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

def build_tree(paths: list[str], limit: int = 50) -> str:
    """Построение дерева файлов"""
    tree = lambda: defaultdict(tree)
    root = tree()

    for path in paths[:limit]:
        parts = path.split("/")
        cur = root
        for p in parts:
            cur = cur[p]

    lines = []

    def render(node, prefix=""):
        total = len(node)
        for i, (name, child) in enumerate(sorted(node.items())):
            connector = "└─ " if i == total - 1 else "├─ "
            lines.append(prefix + connector + name)
            if child:
                extension = "   " if i == total - 1 else "│  "
                render(child, prefix + extension)

    render(root)
    return "\n".join(lines)

def truncate_text(text: str, max_length: int = 4000) -> str:
    """Обрезка текста до максимальной длины"""
    if len(text) > max_length:
        return text[:max_length-3] + "..."
    return text

@dp.inline_query()
async def inline_handler(inline_query: types.InlineQuery):
    """Обработчик инлайн запросов"""
    query = inline_query.query.strip()
    
    if not query or not query.startswith(("http://github.com/", "https://github.com/")):
        return

    logger.info(f"Обработка запроса: {query}")

    repo_info, tree_text, readme_text = await get_repo_info(query)
    
    if not repo_info:
        results = [
            InlineQueryResultArticle(
                id="error",
                title="Ошибка",
                description="Не удалось получить информацию о репозитории",
                input_message_content=InputTextMessageContent(
                    message_text="❌ Не удалось получить информацию о репозитории. Проверьте URL и попробуйте снова.",
                    parse_mode='HTML'
                )
            )
        ]
        await inline_query.answer(results, cache_time=1)
        return

    # Формирование итогового текста
    result_text = (
        f"{repo_info}\n"
        f"<b>📂 Структура файлов:</b>\n<code>{tree_text}</code>\n\n"
        "<b>───────────────────────</b>\n\n"
        f"<b>📖 README:</b>\n<code>{readme_text}</code>"
    )

    # Обрезка текста если превышен лимит Telegram
    result_text = truncate_text(result_text)

    results = [
        InlineQueryResultArticle(
            id="1",
            title="Анализ репозитория GitHub",
            input_message_content=InputTextMessageContent(
                message_text=result_text,
                parse_mode='HTML'
            ),
            description="Показать информацию о репозитории",
            thumb_url="https://github.com/favicon.ico",
            thumb_width=64,
            thumb_height=64
        )
    ]

    await inline_query.answer(results, cache_time=300)  # Кэш на 5 минут
    logger.info(f"Успешно обработан запрос: {query}")

async def main():
    """Основная функция"""
    logger.info("Бот запущен")
    try:
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Ошибка при запуске бота: {e}")
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
