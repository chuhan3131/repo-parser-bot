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
    raise ValueError("BOT_TOKEN not found in .env file")

bot = Bot(token=API_TOKEN)
dp = Dispatcher()

@lru_cache(maxsize=100)
async def get_repo_info(repo_url: str):
    """Asynchronously fetch GitHub repository information with caching"""
    try:
        # Validate URL
        if not is_valid_github_url(repo_url):
            return None, None, None

        parts = repo_url.strip("/").split("/")
        owner, repo = parts[3], parts[4].replace(".git", "")

        async with aiohttp.ClientSession() as session:
            # Fetch main info
            repo_info_url = f"https://api.github.com/repos/{owner}/{repo}"
            async with session.get(repo_info_url) as response:
                if response.status != 200:
                    return None, None, None
                info = await response.json()

            if "message" in info:
                return None, None, None

            # Extract data
            description = info.get("description", "no description") or "no description"
            stars = info.get("stargazers_count", 0)
            language = info.get("language", "not specified")
            default_branch = info.get("default_branch", "main")
            forks_count = info.get("forks_count", 0)
            issues_count = info.get("open_issues_count", 0)
            updated_at = info.get("updated_at", "")

            # Format information
            repo_info = (
                f"<b>📦 Repository: <a href='https://github.com/{owner}'>{owner}</a>/<a href='https://github.com/{owner}/{repo}'>{repo}</a></b>\n"
                f"⭐ <b>Stars:</b> <code>{stars}</code>\n"
                f"💻 <b>Language:</b> <code>{language}</code>\n"
                f"🍴 <b>Forks:</b> <code>{forks_count}</code>\n"
                f"🚨 <b>Issues:</b> <code>{issues_count}</code>\n"
                f"📝 <b>Description:</b> <code>{description}</code>\n"
            )

            # Fetch file tree
            tree_url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/{default_branch}?recursive=1"
            async with session.get(tree_url) as response:
                if response.status == 200:
                    tree_data = await response.json()
                    files = [item["path"] for item in tree_data.get("tree", []) if item["type"] == "blob"]
                    tree_text = build_tree(files, limit=50)
                    if len(files) > 50:
                        tree_text += f"\n...and {len(files) - 50} more files"
                else:
                    tree_text = "Failed to fetch file structure"

            # Fetch README
            readme_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{default_branch}/README.md"
            async with session.get(readme_url) as response:
                if response.status == 200:
                    readme_text = await response.text()
                    readme_text = clean_readme_text(readme_text)
                    if len(readme_text) > 1000:
                        readme_text = readme_text[:1000] + "\n... (truncated)"
                else:
                    readme_text = "README.md not found"

            return repo_info, tree_text, readme_text

    except Exception as e:
        logger.error(f"Error fetching repository info: {e}")
        return None, None, None

def is_valid_github_url(url: str) -> bool:
    """Validate if the URL is a GitHub repository link"""
    return url.startswith(("http://github.com/", "https://github.com/")) and len(url.split("/")) >= 5

def clean_readme_text(text: str) -> str:
    """Clean README from unsupported tags and formatting"""
    text = re.sub(r'<img[^>]*>', '', text)
    text = re.sub(r'!\[.*?\]\(.*?\)', '', text)
    text = text.replace('<', '&lt;').replace('>', '&gt;')
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

def build_tree(paths: list[str], limit: int = 50) -> str:
    """Build a visual file tree"""
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
    """Truncate text to Telegram message limit"""
    if len(text) > max_length:
        return text[:max_length-3] + "..."
    return text

@dp.inline_query()
async def inline_handler(inline_query: types.InlineQuery):
    """Inline query handler"""
    query = inline_query.query.strip()
    
    if not query or not query.startswith(("http://github.com/", "https://github.com/")):
        return

    logger.info(f"Processing query: {query}")

    repo_info, tree_text, readme_text = await get_repo_info(query)
    
    if not repo_info:
        results = [
            InlineQueryResultArticle(
                id="error",
                title="Error",
                description="Failed to fetch repository information",
                input_message_content=InputTextMessageContent(
                    message_text="❌ Failed to fetch repository information. Please check the URL and try again.",
                    parse_mode='HTML'
                )
            )
        ]
        await inline_query.answer(results, cache_time=1)
        return

    # Build final message text
    result_text = (
        f"{repo_info}\n"
        f"<b>📂 File Structure:</b>\n<code>{tree_text}</code>\n\n"
        "<b>───────────────────────</b>\n\n"
        f"<b>📖 README:</b>\n<code>{readme_text}</code>"
    )

    # Truncate if exceeds Telegram message limit
    result_text = truncate_text(result_text)

    results = [
        InlineQueryResultArticle(
            id="1",
            title="GitHub Repository Analysis",
            input_message_content=InputTextMessageContent(
                message_text=result_text,
                parse_mode='HTML'
            ),
            description="Show repository information",
            thumb_url="https://github.com/favicon.ico",
            thumb_width=64,
            thumb_height=64
        )
    ]

    await inline_query.answer(results, cache_time=300)  # Cache for 5 minutes
    logger.info(f"Query successfully processed: {query}")

async def main():
    """Main entry point"""
    logger.info("Bot started")
    try:
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Error while running bot: {e}")
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
