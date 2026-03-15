from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

import aiohttp
from bs4 import BeautifulSoup

import config

log = logging.getLogger(__name__)

OCTOBER_HEADERS = {
    "X-Requested-With": "XMLHttpRequest",
}


@dataclass
class Seat:
    id: int
    row: str
    place: str
    section: str
    price: float
    is_dancefloor: bool = False


@dataclass
class EventSession:
    session_id: int
    date_label: str
    has_tickets: bool


@dataclass
class HockeyEvent:
    title: str
    slug: str
    url: str
    date_info: str = ""
    venue: str = ""
    sessions: list[EventSession] = field(default_factory=list)


class BorisBiletScraper:

    def __init__(self, session: aiohttp.ClientSession | None = None):
        self._own_session = session is None
        self._session = session or aiohttp.ClientSession()

    async def close(self):
        if self._own_session:
            await self._session.close()

    async def login(self, email: str, password: str) -> bool:
        await self._session.get(config.LOGIN_URL)

        headers = {**OCTOBER_HEADERS, "X-OCTOBER-REQUEST-HANDLER": "onLogin"}
        data = {"email": email, "password": password}

        async with self._session.post(
            config.LOGIN_URL, headers=headers, data=data
        ) as resp:
            if resp.status == 200:
                log.info("Успешная авторизация на borisbilet.ru")
                return True
            text = await resp.text()
            log.error("Ошибка авторизации: %s — %s", resp.status, text[:300])
            return False

    async def get_hockey_events(self) -> list[HockeyEvent]:
        async with self._session.get(config.HOCKEY_URL) as resp:
            html = await resp.text()

        soup = BeautifulSoup(html, "html.parser")
        events: list[HockeyEvent] = []

        for card in soup.select("a[href*='/event/']"):
            href = card.get("href", "")
            if "/event/" not in href:
                continue

            slug = href.rstrip("/").split("/")[-1]
            if any(e.slug == slug for e in events):
                continue

            top_spans = [
                ch for ch in card.children
                if getattr(ch, "name", None) == "span"
            ]
            if len(top_spans) < 2:
                continue

            title = top_spans[1].get_text(strip=True)
            if not title:
                continue

            date_info = ""
            venue = ""
            if len(top_spans) >= 3:
                date_spans = [
                    ch for ch in top_spans[2].children
                    if getattr(ch, "name", None) == "span"
                ]
                if len(date_spans) >= 2:
                    date_info = date_spans[0].get_text(strip=True)
                    venue = date_spans[1].get_text(strip=True)
                else:
                    date_info = top_spans[2].get_text(strip=True)

            events.append(
                HockeyEvent(
                    title=title,
                    slug=slug,
                    url=href if href.startswith("http") else config.BASE_URL + href,
                    date_info=date_info,
                    venue=venue,
                )
            )

        log.info("Найдено %d хоккейных мероприятий", len(events))
        return events

    async def get_event_sessions(self, event: HockeyEvent) -> list[EventSession]:
        async with self._session.get(event.url) as resp:
            html = await resp.text()

        soup = BeautifulSoup(html, "html.parser")
        sessions: list[EventSession] = []
        seen_ids: set[int] = set()

        for btn in soup.select("[data-request='onLoadHallScheme']"):
            req_data = btn.get("data-request-data", "")
            match = re.search(r"id:\s*(\d+)", req_data)
            if not match:
                continue

            session_id = int(match.group(1))
            if session_id in seen_ids:
                continue
            seen_ids.add(session_id)

            text_content = btn.get_text(" ", strip=True)
            has_tickets = not any(
                kw in text_content.lower()
                for kw in ["продан", "нет мест", "sold out", "нет билетов"]
            )

            sessions.append(
                EventSession(
                    session_id=session_id,
                    date_label=text_content,
                    has_tickets=has_tickets,
                )
            )

        event.sessions = sessions
        return sessions

    async def get_available_seats(
        self, event_url: str, session_id: int
    ) -> list[Seat]:
        headers = {
            **OCTOBER_HEADERS,
            "X-OCTOBER-REQUEST-HANDLER": "onLoadHallScheme",
        }
        data = {"id": session_id}

        async with self._session.post(
            event_url, headers=headers, data=data
        ) as resp:
            raw = await resp.text()

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            log.error("Не удалось распарсить ответ схемы зала")
            return []

        raw_seats = None
        seats: list[Seat] = []

        for value in payload.values():
            if isinstance(value, dict) and "seats" in value:
                raw_seats = value["seats"]
                break

        if raw_seats is None:
            html_content = ""
            for value in payload.values():
                if isinstance(value, str):
                    html_content += value

            seats_idx = html_content.find('"seats":[')
            if seats_idx == -1:
                seats_idx = html_content.find('"seats" :[')
            if seats_idx == -1:
                log.debug("Данные о местах не найдены (вероятно, все продано)")
                return []

            array_start = html_content.index("[", seats_idx)
            decoder = json.JSONDecoder()
            try:
                raw_seats, _ = decoder.raw_decode(html_content, array_start)
            except json.JSONDecodeError:
                log.error("Не удалось распарсить массив мест")
                return seats

        for s in raw_seats:
            price = s.get("price", 0)
            if price <= 0:
                continue
            seats.append(
                Seat(
                    id=s["id"],
                    row=str(s.get("rowNum", "")),
                    place=str(s.get("placeNum", "")),
                    section=s.get("levelName", ""),
                    price=price,
                    is_dancefloor=s.get("isDancefloor", False),
                )
            )

        log.info(
            "Сеанс %d: %d доступных мест из %d",
            session_id,
            len(seats),
            len(raw_seats),
        )
        return seats
