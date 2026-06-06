import asyncio
import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Page, BrowserContext

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
]

_STEALTH_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
window.chrome = {runtime: {}};
"""


def random_ua() -> str:
    return random.choice(_USER_AGENTS)


def random_viewport() -> dict:
    return {
        "width": random.randint(1280, 1440),
        "height": random.randint(768, 900),
    }


async def apply_stealth(context: "BrowserContext") -> None:
    try:
        from playwright_stealth import stealth_async
        await stealth_async(context)
    except ImportError:
        pass
    await context.add_init_script(_STEALTH_SCRIPT)


async def human_delay(min_ms: int = 800, max_ms: int = 2500) -> None:
    await asyncio.sleep(random.uniform(min_ms / 1000, max_ms / 1000))


async def human_click_delay(min_ms: int = 300, max_ms: int = 1200) -> None:
    await asyncio.sleep(random.uniform(min_ms / 1000, max_ms / 1000))


def _bezier(t: float, p0: float, p1: float, p2: float, p3: float) -> float:
    return (
        (1 - t) ** 3 * p0
        + 3 * (1 - t) ** 2 * t * p1
        + 3 * (1 - t) * t ** 2 * p2
        + t ** 3 * p3
    )


async def human_move_and_click(page: "Page", x: int, y: int) -> None:
    vp = page.viewport_size or {"width": 1280, "height": 800}
    sx = random.randint(0, vp["width"])
    sy = random.randint(0, vp["height"])
    cp1x = random.randint(min(sx, x), max(sx, x))
    cp1y = random.randint(min(sy, y), max(sy, y))
    cp2x = random.randint(min(sx, x), max(sx, x))
    cp2y = random.randint(min(sy, y), max(sy, y))
    steps = random.randint(20, 40)
    for i in range(steps + 1):
        t = i / steps
        mx = int(_bezier(t, sx, cp1x, cp2x, x))
        my = int(_bezier(t, sy, cp1y, cp2y, y))
        await page.mouse.move(mx, my)
        await asyncio.sleep(random.uniform(0.005, 0.015))
    await asyncio.sleep(random.uniform(0.1, 0.3))
    await page.mouse.click(x, y)


async def human_type(page: "Page", selector: str, text: str) -> None:
    await page.click(selector)
    await human_click_delay(200, 500)
    for char in text:
        await page.keyboard.type(char, delay=random.uniform(80, 250))
        if random.random() < 0.05:
            await asyncio.sleep(random.uniform(0.3, 0.8))


async def scroll_to_read(page: "Page") -> None:
    height = await page.evaluate("document.body.scrollHeight")
    steps = random.randint(3, 7)
    for _ in range(steps):
        scroll_to = random.randint(100, max(200, height // max(steps, 1)))
        await page.evaluate(f"window.scrollBy(0, {scroll_to})")
        await asyncio.sleep(random.uniform(0.4, 1.2))
