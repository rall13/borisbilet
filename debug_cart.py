import asyncio
import re
import aiohttp
from bs4 import BeautifulSoup


async def main():
    async with aiohttp.ClientSession() as s:
        # Login first
        await s.get("https://www.borisbilet.ru/login")
        headers = {
            "X-Requested-With": "XMLHttpRequest",
            "X-OCTOBER-REQUEST-HANDLER": "onLogin",
        }
        from config import BORIS_EMAIL, BORIS_PASSWORD
        if BORIS_EMAIL and BORIS_PASSWORD:
            await s.post(
                "https://www.borisbilet.ru/login",
                headers=headers,
                data={"email": BORIS_EMAIL, "password": BORIS_PASSWORD},
            )
            print("Logged in")

        # Select a seat and add to cart
        event_url = "https://www.borisbilet.ru/event/v-dzhaze-tolko-devushki"
        session_id = 2377

        h2 = {
            "X-Requested-With": "XMLHttpRequest",
            "X-OCTOBER-REQUEST-HANDLER": "appEvent::onSelectSeat",
        }
        await s.post(event_url, headers=h2, data={"seat_id": 1010, "event_id": session_id})
        print("Seat selected")

        h3 = {
            "X-Requested-With": "XMLHttpRequest",
            "X-OCTOBER-REQUEST-HANDLER": "appEvent::onAddToCart",
        }
        async with s.post(event_url, headers=h3, data={"event_id": session_id}) as resp:
            cart_resp = await resp.text()
            print(f"Add to cart status: {resp.status}")

        # Now fetch cart page
        async with s.get("https://www.borisbilet.ru/cart") as r:
            html = await r.text()

        soup = BeautifulSoup(html, "html.parser")
        for el in soup.select("[data-request]"):
            req = el.get("data-request")
            data = el.get("data-request-data", "")
            tag = el.name
            text = el.get_text(" ", strip=True)[:80]
            print(f"  <{tag}> handler={req} data={data} text={text}")

        # Also look for any booking/reserve forms
        for form in soup.select("form"):
            action = form.get("action", "")
            method = form.get("method", "")
            dreq = form.get("data-request", "")
            print(f"  FORM action={action} method={method} data-request={dreq}")

        # Look for buttons with booking text
        for btn in soup.select("button, a.btn-primary, [type=submit]"):
            text = btn.get_text(strip=True)[:60]
            req = btn.get("data-request", "")
            href = btn.get("href", "")
            if text:
                print(f"  BTN text={text} handler={req} href={href}")


asyncio.run(main())
