import asyncio
import aiohttp

HANDLERS = [
    "appCart::onOrder",
    "appCart::onBuy",
    "appCart::onPurchase",
    "appCart::onSaveOrder",
    "appCart::onProcessOrder",
    "appCart::onCompleteOrder",
    "appCart::onFinishOrder",
    "appCart::onSetDeliveryType",
    "appCart::onSetOrderType",
    "appCart::onSelectDelivery",
    "appCart::onApplyOrder",
    "appCart::onBookTickets",
    "appCart::onReserveTickets",
    "onOrder",
    "onBuy",
    "onPurchase",
    "onSaveOrder",
    "onProcessOrder",
    "onBookTickets",
    "onReserveTickets",
    "onSetDeliveryType",
    "onApplyOrder",
    "onFinishOrder",
    "onCompleteOrder",
    "appOrder::onCreateOrder",
    "appOrder::onSubmit",
    "appOrder::onBook",
    "appOrder::onReserve",
    "appOrder::onPlaceOrder",
    "appOrder::onSave",
    "appCheckout::onSubmit",
    "appCheckout::onOrder",
    "appCheckout::onBook",
]


async def main():
    async with aiohttp.ClientSession() as s:
        for h in HANDLERS:
            headers = {
                "X-Requested-With": "XMLHttpRequest",
                "X-OCTOBER-REQUEST-HANDLER": h,
            }
            async with s.post(
                "https://www.borisbilet.ru/cart", headers=headers, data={}
            ) as resp:
                status = resp.status
                text = await resp.text()
                found = "не найден" not in text
                if found:
                    print(f"  >>> {status} FOUND — {h}  resp={text[:200]}")
                else:
                    print(f"  {status} — {h}")


asyncio.run(main())
