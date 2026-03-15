import asyncio
import re
import sys

import aiohttp
from bs4 import BeautifulSoup

BASE = "https://www.borisbilet.ru"
AJAX_HEADERS = {"X-Requested-With": "XMLHttpRequest"}


async def main():
    if len(sys.argv) < 3:
        print("Использование: python _discover.py email password")
        return

    email, password = sys.argv[1], sys.argv[2]

    async with aiohttp.ClientSession() as s:
        await s.get(f"{BASE}/login")
        headers = {**AJAX_HEADERS, "X-OCTOBER-REQUEST-HANDLER": "onLogin"}
        async with s.post(f"{BASE}/login", headers=headers, data={"email": email, "password": password}) as r:
            if r.status != 200:
                print(f"Ошибка входа: {r.status}")
                return
            print("Авторизация OK")

        events_url = f"{BASE}/events/hokkey"
        async with s.get(events_url) as r:
            html = await r.text()

        soup = BeautifulSoup(html, "html.parser")
        event_url = None
        for a in soup.select("a[href*='/event/']"):
            href = a.get("href", "")
            if "/event/" in href:
                event_url = href if href.startswith("http") else BASE + href
                break

        if not event_url:
            print("Не нашёл мероприятий, проверяю корзину напрямую...")
        else:
            print(f"Мероприятие: {event_url}")
            async with s.get(event_url) as r:
                ehtml = await r.text()

            esoup = BeautifulSoup(ehtml, "html.parser")
            session_id = None
            for btn in esoup.select("[data-request='onLoadHallScheme']"):
                m = re.search(r"id:\s*(\d+)", btn.get("data-request-data", ""))
                if m:
                    session_id = int(m.group(1))
                    break

            if session_id:
                print(f"Session ID: {session_id}")
                h = {**AJAX_HEADERS, "X-OCTOBER-REQUEST-HANDLER": "onLoadHallScheme"}
                async with s.post(event_url, headers=h, data={"id": session_id}) as r:
                    import json
                    payload = json.loads(await r.text())

                raw_seats = None
                for v in payload.values():
                    if isinstance(v, dict) and "seats" in v:
                        raw_seats = v["seats"]
                        break

                if raw_seats is None:
                    hc = "".join(v for v in payload.values() if isinstance(v, str))
                    idx = hc.find('"seats":[')
                    if idx >= 0:
                        arr_start = hc.index("[", idx)
                        raw_seats, _ = json.JSONDecoder().raw_decode(hc, arr_start)

                if raw_seats:
                    available = [s for s in raw_seats if s.get("price", 0) > 0]
                    if available:
                        seat = available[0]
                        print(f"Выбираю место: id={seat['id']}")
                        h2 = {**AJAX_HEADERS, "X-OCTOBER-REQUEST-HANDLER": "appEvent::onSelectSeat"}
                        async with s.post(event_url, headers=h2, data={"seat_id": seat["id"], "event_id": session_id}) as r:
                            print(f"  select: {r.status}")

                        h3 = {**AJAX_HEADERS, "X-OCTOBER-REQUEST-HANDLER": "appEvent::onAddToCart"}
                        async with s.post(event_url, headers=h3, data={"event_id": session_id}) as r:
                            print(f"  add_to_cart: {r.status}")
                    else:
                        print("Нет доступных мест")
                else:
                    print("Не удалось получить места")

        print("\n=== Загружаю страницу корзины ===")
        async with s.get(f"{BASE}/cart") as r:
            cart_html = await r.text()

        with open("_cart_auth.html", "w", encoding="utf-8") as f:
            f.write(cart_html)

        cart_soup = BeautifulSoup(cart_html, "html.parser")

        print("\nВсе data-request:")
        for el in cart_soup.select("[data-request]"):
            handler = el.get("data-request")
            req_data = el.get("data-request-data", "")
            tag = el.name
            text = el.get_text(" ", strip=True)[:80]
            print(f"  [{tag}] data-request=\"{handler}\" data-request-data=\"{req_data}\"")
            if text:
                print(f"         text: {text}")

        print("\nВсе формы:")
        for form in cart_soup.select("form"):
            action = form.get("action", "")
            method = form.get("method", "")
            dr = form.get("data-request", "")
            print(f"  <form action=\"{action}\" method=\"{method}\" data-request=\"{dr}\">")
            for inp in form.select("input, select, textarea, button"):
                name = inp.get("name", "")
                typ = inp.get("type", "")
                val = inp.get("value", "")
                dr2 = inp.get("data-request", "")
                txt = inp.get_text(" ", strip=True)[:50]
                print(f"    <{inp.name} name=\"{name}\" type=\"{typ}\" value=\"{val}\" data-request=\"{dr2}\"> {txt}")

        print("\nВсе кнопки:")
        for btn in cart_soup.select("button, [type='submit'], .btn-primary, .btn-secondary"):
            handler = btn.get("data-request", "")
            onclick = btn.get("onclick", "")
            xclick = btn.get("@click", "")
            text = btn.get_text(" ", strip=True)[:80]
            print(f"  text=\"{text}\" data-request=\"{handler}\" onclick=\"{onclick}\" @click=\"{xclick}\"")


asyncio.run(main())
