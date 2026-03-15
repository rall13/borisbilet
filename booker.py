from __future__ import annotations

import json
import logging
from dataclasses import dataclass

import config
from scraper import OCTOBER_HEADERS, BorisBiletScraper, HockeyEvent, Seat

log = logging.getLogger(__name__)


@dataclass
class BookingResult:
    success: bool
    event_title: str
    booked_seats: list[Seat]
    failed_seats: list[Seat]
    message: str = ""


class AutoBooker:

    def __init__(self, scraper: BorisBiletScraper):
        self.scraper = scraper
        self._session = scraper._session

    async def select_seat(
        self, event_url: str, session_id: int, seat_id: int
    ) -> bool:
        headers = {
            **OCTOBER_HEADERS,
            "X-OCTOBER-REQUEST-HANDLER": "appEvent::onSelectSeat",
        }
        data = {"seat_id": seat_id, "event_id": session_id}

        try:
            async with self._session.post(
                event_url, headers=headers, data=data
            ) as resp:
                if resp.status == 200:
                    log.info("Место %d выбрано", seat_id)
                    return True
                text = await resp.text()
                log.warning(
                    "Не удалось выбрать место %d: %s — %s",
                    seat_id, resp.status, text[:200],
                )
                return False
        except Exception as e:
            log.error("Ошибка при выборе места %d: %s", seat_id, e)
            return False

    async def add_to_cart(self, event_url: str, session_id: int) -> bool:
        headers = {
            **OCTOBER_HEADERS,
            "X-OCTOBER-REQUEST-HANDLER": "appEvent::onAddToCart",
        }
        data = {"event_id": session_id}

        try:
            async with self._session.post(
                event_url, headers=headers, data=data
            ) as resp:
                if resp.status == 200:
                    body = await resp.text()
                    try:
                        result = json.loads(body)
                        if "error" in str(result).lower():
                            log.warning("Ответ корзины содержит ошибку: %s", body[:300])
                            return False
                    except json.JSONDecodeError:
                        pass
                    log.info("Места добавлены в корзину")
                    return True
                text = await resp.text()
                log.warning(
                    "Не удалось добавить в корзину: %s — %s",
                    resp.status, text[:200],
                )
                return False
        except Exception as e:
            log.error("Ошибка при добавлении в корзину: %s", e)
            return False

    async def confirm_booking(self) -> bool:
        headers = {
            **OCTOBER_HEADERS,
            "X-OCTOBER-REQUEST-HANDLER": "appCart::onSubmit",
        }
        data = {"mode": "booking"}

        try:
            async with self._session.post(
                config.CART_URL, headers=headers, data=data
            ) as resp:
                if resp.status == 200:
                    body = await resp.text()
                    try:
                        result = json.loads(body)
                        if "X_OCTOBER_REDIRECT" in result:
                            log.info("Бронирование подтверждено! Redirect: %s", result["X_OCTOBER_REDIRECT"])
                            return True
                    except json.JSONDecodeError:
                        pass
                    log.info("Бронирование подтверждено (status 200)")
                    return True
                text = await resp.text()
                log.warning("Не удалось подтвердить бронь: %s — %s", resp.status, text[:300])
                return False
        except Exception as e:
            log.error("Ошибка при подтверждении бронирования: %s", e, exc_info=True)
            return False

    async def book_event(
        self, event: HockeyEvent, max_tickets: int = 0
    ) -> BookingResult:
        if max_tickets <= 0:
            max_tickets = config.MAX_TICKETS

        sessions = await self.scraper.get_event_sessions(event)
        if not sessions:
            return BookingResult(
                success=False, event_title=event.title,
                booked_seats=[], failed_seats=[],
                message="Сеансы не найдены",
            )

        for session in sessions:
            if not session.has_tickets:
                continue

            seats = await self.scraper.get_available_seats(
                event.url, session.session_id
            )
            if not seats:
                continue

            target_seats = sorted(seats, key=lambda s: s.price)[:max_tickets]

            booked: list[Seat] = []
            failed: list[Seat] = []

            for seat in target_seats:
                ok = await self.select_seat(
                    event.url, session.session_id, seat.id
                )
                if ok:
                    booked.append(seat)
                else:
                    failed.append(seat)

            if booked:
                cart_ok = await self.add_to_cart(event.url, session.session_id)
                if not cart_ok:
                    return BookingResult(
                        success=False, event_title=event.title,
                        booked_seats=[], failed_seats=booked + failed,
                        message="Места выбраны, но не удалось добавить в корзину",
                    )

                confirm_ok = await self.confirm_booking()
                if confirm_ok:
                    return BookingResult(
                        success=True, event_title=event.title,
                        booked_seats=booked, failed_seats=failed,
                        message=f"Забронировано {len(booked)} билетов на {session.date_label}",
                    )
                else:
                    return BookingResult(
                        success=False, event_title=event.title,
                        booked_seats=booked, failed_seats=failed,
                        message="Билеты в корзине, но не удалось подтвердить бронь. Подтвердите вручную на сайте: "
                               + config.CART_URL,
                    )

        return BookingResult(
            success=False, event_title=event.title,
            booked_seats=[], failed_seats=[],
            message="Нет доступных мест ни в одном сеансе",
        )
