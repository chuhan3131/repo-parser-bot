import asyncio
import requests
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineQueryResultArticle, InputTextMessageContent

API_TOKEN = "token"

bot = Bot(token=API_TOKEN)
dp = Dispatcher()


def get_repo_info(repo_url: str):
    parts = repo_url.strip("/").split("/")
    if "github.com" not in repo_url or len(parts) < 5:
        return None, None, None

    owner, repo = parts[3], parts[4].replace(".git", "")

    repo_info_url = f"https://api.github.com/repos/{owner}/{repo}"
    info = requests.get(repo_info_url).json()

    if "message" in info:
        return None, None, None

    description = info.get("description", "нет описания")
    stars = info.get("stargazers_count", 0)
    language = info.get("language", "не указан")
    default_branch = info.get("default_branch", "main")

    repo_info = (
        f"<b>📦 Репозиторий: <a href='https://github.com/{owner}'>{owner}</a>/<a href='https://github.com/{owner}/{repo}'>{repo}</a>\n"
        f"⭐ Звёзды: <code>{stars}</code>\n"
        f"💻 ЯП: <code>{language}</code>\n"
        f"📝 Описание: <code>{description}</code></b>\n"
    )

    tree_url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/{default_branch}?recursive=1"
    tree_data = requests.get(tree_url).json()

    files = [item["path"] for item in tree_data.get("tree", []) if item["type"] == "blob"]

    tree_text = build_tree(files, limit=50)
    if len(files) > 50:
        tree_text += f"\n...и ещё {len(files) - 50} файлов"

    readme_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{default_branch}/README.md"
    readme_resp = requests.get(readme_url)

    if readme_resp.status_code == 200:
        readme_text = readme_resp.text[:1000]
        if len(readme_resp.text) > 1000:
            readme_text += "\n... (обрезано)"
    else:
        readme_text = "README.md не найден"

    return repo_info, tree_text, readme_text


def build_tree(paths: list[str], limit: int = 50) -> str:
    from collections import defaultdict

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
    if len(paths) > limit:
        lines.append(f"... и ещё {len(paths) - limit} файлов")

    return "\n".join(lines)



@dp.inline_query()
async def inline_handler(inline_query: types.InlineQuery):
    query = inline_query.query.strip()

    if not query.startswith("http"):
        return

    repo_info, tree_text, readme_text = get_repo_info(query)
    if not repo_info:
        return

    result_text = (
        f"{repo_info}\n"
        f"<b>📂 Структура:</b>\n<code>{tree_text}</code>\n\n"
        "<b>==============================</b>\n\n"
        f"<b>📖 README:</b>\n<code>{readme_text}</code>"
    )

    results = [
        InlineQueryResultArticle(
            id="1",
            title="разбор репозитория",
            input_message_content=InputTextMessageContent(
                message_text=result_text,
                parse_mode='HTML'
            ),
            description="by github.com/chuhan3131"
        )
    ]

    await inline_query.answer(results, cache_time=1)


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
