from __future__ import annotations

import asyncio
import logging

import aiohttp
from aiogram import Bot, Dispatcher, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

import config
from booker import AutoBooker, BookingResult
from scraper import BorisBiletScraper, HockeyEvent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

router = Router()


class AppState:
    def __init__(self):
        self.monitoring: bool = False
        self.monitor_task: asyncio.Task | None = None
        self.logged_in: bool = False
        self.max_tickets: int = config.MAX_TICKETS
        self.poll_interval: int = config.POLL_INTERVAL
        self.known_events: set[str] = set()
        self.notified_available: set[str] = set()
        self.booked_events: set[str] = set()
        self.auto_book: bool = False
        self.http_session: aiohttp.ClientSession | None = None
        self.scraper: BorisBiletScraper | None = None
        self.booker: AutoBooker | None = None
        self.bot: Bot | None = None


state = AppState()


def is_admin(message: Message) -> bool:
    return message.chat.id == config.ADMIN_CHAT_ID


def _ensure_scraper():
    if state.http_session is None:
        state.http_session = aiohttp.ClientSession()
    if state.scraper is None:
        state.scraper = BorisBiletScraper(state.http_session)
    if state.booker is None:
        state.booker = AutoBooker(state.scraper)


async def _notify(text: str):
    if state.bot and config.ADMIN_CHAT_ID:
        await state.bot.send_message(config.ADMIN_CHAT_ID, text, parse_mode="HTML")


def _format_booking_result(result: BookingResult) -> str:
    if result.success:
        lines = [f"<b>Забронировано!</b> {result.event_title}"]
        lines.append(result.message)
        for s in result.booked_seats:
            lines.append(f"  - {s.section}, ряд {s.row}, место {s.place} — {s.price}₽")
        return "\n".join(lines)
    return f"<b>Не удалось забронировать</b> {result.event_title}\n{result.message}"


@router.message(CommandStart())
async def cmd_start(message: Message):
    chat_id = message.chat.id

    if config.ADMIN_CHAT_ID == 0:
        config.ADMIN_CHAT_ID = chat_id
        log.info("Администратор зарегистрирован: chat_id=%d", chat_id)
        await message.answer(
            f"<b>Вы зарегистрированы как администратор!</b>\n"
            f"Ваш chat_id: <code>{chat_id}</code>\n\n"
            f"Сохраните его в .env → ADMIN_CHAT_ID={chat_id}",
            parse_mode="HTML",
        )

    if not is_admin(message):
        await message.answer(
            f"Бот доступен только администратору.\n"
            f"Ваш chat_id: <code>{chat_id}</code>",
            parse_mode="HTML",
        )
        return

    await message.answer(
        "<b>Бот автобронирования билетов на хоккей</b>\n"
        "borisbilet.ru — ХК Ижсталь\n\n"
        "<b>Команды:</b>\n"
        "/login — авторизоваться на сайте\n"
        "/events — список хоккейных мероприятий\n"
        "/monitor — запустить мониторинг новых билетов\n"
        "/stop — остановить мониторинг\n"
        "/status — текущий статус\n"
        "/book &lt;slug&gt; — забронировать вручную\n"
        "/set_max &lt;N&gt; — макс. билетов (1-10)\n"
        "/set_interval &lt;сек&gt; — интервал проверки\n",
        parse_mode="HTML",
    )


@router.message(Command("login"))
async def cmd_login(message: Message):
    if not is_admin(message):
        return

    if not config.BORIS_EMAIL or not config.BORIS_PASSWORD:
        await message.answer(
            "Учётные данные не настроены. Укажите BORIS_EMAIL и BORIS_PASSWORD в .env"
        )
        return

    _ensure_scraper()
    await message.answer("Авторизуюсь на borisbilet.ru...")

    ok = await state.scraper.login(config.BORIS_EMAIL, config.BORIS_PASSWORD)
    state.logged_in = ok

    if ok:
        await message.answer("Авторизация успешна!")
    else:
        await message.answer("Ошибка авторизации. Проверьте данные в .env")


@router.message(Command("events"))
async def cmd_events(message: Message):
    if not is_admin(message):
        return

    _ensure_scraper()
    await message.answer("Загружаю список хоккейных мероприятий...")

    events = await state.scraper.get_hockey_events()
    if not events:
        await message.answer("Хоккейных мероприятий не найдено.")
        return

    lines = ["<b>Хоккейные мероприятия:</b>\n"]
    for i, ev in enumerate(events, 1):
        parts = [f"{i}. <b>{ev.title}</b>"]
        if ev.date_info:
            parts.append(f"   {ev.date_info}")
        if ev.venue:
            parts.append(f"   {ev.venue}")
        parts.append(f"   slug: <code>{ev.slug}</code>")
        parts.append(f"   URL: {ev.url}")
        lines.append("\n".join(parts))

    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(Command("status"))
async def cmd_status(message: Message):
    if not is_admin(message):
        return

    status_lines = [
        "<b>Статус бота:</b>\n",
        f"Авторизация: {'да' if state.logged_in else 'нет'}",
        f"Мониторинг: {'запущен' if state.monitoring else 'остановлен'}",
        f"Авто-бронь: {'вкл' if state.auto_book else 'выкл'}",
        f"Макс. билетов: {state.max_tickets}",
        f"Интервал: {state.poll_interval} сек",
        f"Известные события: {len(state.known_events)}",
    ]
    await message.answer("\n".join(status_lines), parse_mode="HTML")


@router.message(Command("set_max"))
async def cmd_set_max(message: Message):
    if not is_admin(message):
        return

    parts = message.text.strip().split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer("Использование: /set_max <число от 1 до 10>")
        return

    n = int(parts[1])
    if n < 1 or n > 10:
        await message.answer("Число должно быть от 1 до 10")
        return

    state.max_tickets = n
    await message.answer(f"Макс. билетов установлено: {n}")


@router.message(Command("set_interval"))
async def cmd_set_interval(message: Message):
    if not is_admin(message):
        return

    parts = message.text.strip().split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer("Использование: /set_interval <секунды>")
        return

    n = int(parts[1])
    if n < 5:
        await message.answer("Минимальный интервал: 5 секунд")
        return

    state.poll_interval = n
    await message.answer(f"Интервал проверки: {n} сек")


@router.message(Command("book"))
async def cmd_book(message: Message):
    if not is_admin(message):
        return

    parts = message.text.strip().split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(
            "Использование: /book &lt;slug&gt;\nУзнайте slug через /events",
            parse_mode="HTML",
        )
        return

    slug = parts[1].strip()
    _ensure_scraper()

    if not state.logged_in:
        await message.answer("Сначала авторизуйтесь: /login")
        return

    event = HockeyEvent(
        title=slug, slug=slug,
        url=f"{config.BASE_URL}/event/{slug}",
    )

    await message.answer(f"Бронирую билеты на <b>{slug}</b>...", parse_mode="HTML")

    result = await state.booker.book_event(event, state.max_tickets)
    await message.answer(_format_booking_result(result), parse_mode="HTML")


@router.message(Command("monitor"))
async def cmd_monitor(message: Message):
    if not is_admin(message):
        return

    if state.monitoring:
        await message.answer("Мониторинг уже запущен.")
        return

    _ensure_scraper()

    if not state.logged_in and (config.BORIS_EMAIL and config.BORIS_PASSWORD):
        await message.answer("Автоматическая авторизация...")
        ok = await state.scraper.login(config.BORIS_EMAIL, config.BORIS_PASSWORD)
        state.logged_in = ok
        if not ok:
            await message.answer(
                "Авторизация не удалась. Мониторинг запущен без автобронирования."
            )

    events = await state.scraper.get_hockey_events()
    state.known_events = {e.slug for e in events}

    state.monitoring = True
    state.monitor_task = asyncio.create_task(_monitor_loop())
    await message.answer(
        f"Мониторинг запущен!\n"
        f"Известно мероприятий: {len(state.known_events)}\n"
        f"Интервал: {state.poll_interval} сек\n"
        f"Автобронь: {'вкл' if (state.auto_book and state.logged_in) else 'выкл'}"
    )


@router.message(Command("stop"))
async def cmd_stop(message: Message):
    if not is_admin(message):
        return

    if not state.monitoring:
        await message.answer("Мониторинг не запущен.")
        return

    state.monitoring = False
    if state.monitor_task:
        state.monitor_task.cancel()
        state.monitor_task = None

    await message.answer("Мониторинг остановлен.")


async def _monitor_loop():
    while state.monitoring:
        try:
            await _check_for_new_events()
        except asyncio.CancelledError:
            break
        except Exception as e:
            log.error("Ошибка в цикле мониторинга: %s", e, exc_info=True)
            await _notify(f"Ошибка мониторинга: {e}")

        try:
            await asyncio.sleep(state.poll_interval)
        except asyncio.CancelledError:
            break


async def _check_for_new_events():
    events = await state.scraper.get_hockey_events()

    for event in events:
        if event.slug in state.known_events:
            continue

        state.known_events.add(event.slug)

        sessions = await state.scraper.get_event_sessions(event)
        available_sessions = [s for s in sessions if s.has_tickets]

        if not available_sessions:
            await _notify(
                f"<b>Новое мероприятие (без билетов):</b>\n"
                f"{event.title}\n"
                f"<a href=\"{event.url}\">Открыть</a>"
            )
            continue

        total_seats = 0
        for s in available_sessions:
            seats = await state.scraper.get_available_seats(event.url, s.session_id)
            total_seats += len(seats)

        await _notify(
            f"<b>Новое мероприятие с билетами!</b>\n"
            f"{event.title}\n"
            f"Доступно мест: ~{total_seats}\n"
            f"<a href=\"{event.url}\">Открыть</a>"
        )

        if state.auto_book and state.logged_in:
            await _notify("Начинаю автобронирование...")
            result = await state.booker.book_event(event, state.max_tickets)
            await _notify(_format_booking_result(result))
            if result.success:
                state.booked_events.add(event.slug)

    for event in events:
        if event.slug in state.booked_events:
            continue

        sessions = await state.scraper.get_event_sessions(event)
        for s in sessions:
            key = f"{event.slug}:{s.session_id}"
            if key in state.notified_available:
                continue
            if not s.has_tickets:
                continue

            seats = await state.scraper.get_available_seats(event.url, s.session_id)
            if not seats:
                continue

            state.notified_available.add(key)

            await _notify(
                f"<b>Появились билеты!</b>\n"
                f"{event.title} — {s.date_label}\n"
                f"Доступно мест: {len(seats)}\n"
                f"<a href=\"{event.url}\">Открыть</a>"
            )

            if state.auto_book and state.logged_in:
                result = await state.booker.book_event(event, state.max_tickets)
                await _notify(_format_booking_result(result))
                if result.success:
                    state.booked_events.add(event.slug)


async def main():
    if not config.TELEGRAM_BOT_TOKEN:
        log.error("TELEGRAM_BOT_TOKEN не указан в .env")
        return

    bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
    state.bot = bot
    dp = Dispatcher()
    dp.include_router(router)

    log.info("Бот запущен. Ожидание команд...")

    try:
        await dp.start_polling(bot)
    finally:
        if state.http_session:
            await state.http_session.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
