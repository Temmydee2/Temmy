import os
import re
import time
import requests

# =========================================================
# TEMMYDEEXC — RENDER TELEGRAM TOKEN SCANNER
# READ-ONLY — NO BUYING / SELLING
# =========================================================

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")

if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN environment variable is missing.")

CHAINS = {
    "solana": "solana",
    "bnb": "bsc",
    "robinhood": "robinhood",
}


def get_pairs(chain, token):
    if chain not in CHAINS:
        raise ValueError(f"Unsupported chain: {chain}")

    url = (
        f"https://api.dexscreener.com/token-pairs/v1/"
        f"{CHAINS[chain]}/{token}"
    )

    response = requests.get(url, timeout=20)
    response.raise_for_status()

    data = response.json()

    if not isinstance(data, list):
        raise ValueError("Unexpected DexScreener response.")

    return data


def analyze_token(chain, token):
    pairs = get_pairs(chain, token)

    valid_pairs = [
        p for p in pairs
        if p.get("liquidity", {}).get("usd") is not None
    ]

    if not valid_pairs:
        raise ValueError("No usable token/pool data found.")

    valid_pairs.sort(
        key=lambda p: p.get("liquidity", {}).get("usd", 0) or 0,
        reverse=True
    )

    liquidity = sum(
        p.get("liquidity", {}).get("usd", 0) or 0
        for p in valid_pairs
    )

    volume = sum(
        p.get("volume", {}).get("h24", 0) or 0
        for p in valid_pairs
    )

    buys = 0
    sells = 0

    for p in valid_pairs:
        txns = p.get("txns", {}).get("h24", {})
        buys += txns.get("buys", 0) or 0
        sells += txns.get("sells", 0) or 0

    trades = buys + sells

    buy_pressure = (
        buys / trades * 100
        if trades
        else 0
    )

    volume_liquidity = (
        volume / liquidity
        if liquidity
        else 0
    )

    strongest = valid_pairs[0]

    base = strongest.get("baseToken", {})

    name = base.get("name", "Unknown")
    symbol = base.get("symbol", "Unknown")
    price = strongest.get("priceUsd", "Unknown")

    # =====================================================
    # BASIC RISK SCORE
    # =====================================================

    score = 100
    flags = []

    if liquidity < 5000:
        score -= 35
        flags.append("🔴 Very low liquidity")

    elif liquidity < 10000:
        score -= 20
        flags.append("🟠 Low liquidity")

    elif liquidity < 50000:
        score -= 10
        flags.append("🟡 Moderate liquidity")

    if volume_liquidity > 30:
        score -= 20
        flags.append("🟠 Extremely high volume/liquidity")

    elif volume_liquidity > 10:
        score -= 10
        flags.append("🟡 High volume/liquidity")

    if trades:
        if buy_pressure < 45:
            score -= 20
            flags.append("🔴 Strong sell pressure")

        elif buy_pressure < 50:
            score -= 10
            flags.append("🟠 Sell pressure")

    score = max(0, min(100, score))

    if score >= 80:
        rating = "🟢 LOWER RISK — INVESTIGATE"

    elif score >= 60:
        rating = "🟡 MODERATE RISK"

    elif score >= 40:
        rating = "🟠 HIGH RISK"

    else:
        rating = "🔴 EXTREME RISK"

    return {
        "chain": chain,
        "token": token,
        "name": name,
        "symbol": symbol,
        "price": price,
        "liquidity": liquidity,
        "volume": volume,
        "buys": buys,
        "sells": sells,
        "buy_pressure": buy_pressure,
        "volume_liquidity": volume_liquidity,
        "pools": len(valid_pairs),
        "score": score,
        "rating": rating,
        "flags": flags,
        "dex": strongest.get("dexId", "Unknown"),
        "url": strongest.get("url", ""),
    }


def make_alert(data):
    flags = data["flags"]

    risk_flags = (
        "\n".join(flags)
        if flags
        else "✅ No basic risk flags detected"
    )

    return f"""🤖 TEMMYDEEXC SCANNER

⛓️ Chain: {data["chain"].upper()}

🪙 {data["name"]} (${data["symbol"]})

💰 Price:
${data["price"]}

💧 Liquidity:
${data["liquidity"]:,.2f}

📊 24h Volume:
${data["volume"]:,.2f}

📈 Buys: {data["buys"]}
📉 Sells: {data["sells"]}

⚖️ Buy pressure:
{data["buy_pressure"]:.1f}%

🔥 Volume/Liquidity:
{data["volume_liquidity"]:.2f}x

🏊 Pools:
{data["pools"]}

🏆 Main DEX:
{data["dex"]}

🧠 SCORE:
{data["score"]}/100

{data["rating"]}

🚨 RISK FLAGS:
{risk_flags}

⚠️ READ-ONLY ANALYSIS
No automatic buying or selling.

Holder concentration, deployer history,
and deeper contract checks are not included yet.

🔎 Research before trading.

{data["url"]}
"""


def looks_like_solana(address):
    return bool(
        re.fullmatch(
            r"[1-9A-HJ-NP-Za-km-z]{32,44}",
            address
        )
    )


def looks_like_evm(address):
    return bool(
        re.fullmatch(
            r"0x[a-fA-F0-9]{40}",
            address
        )
    )


def scan_automatic(token):
    # =====================================================
    # SOLANA
    # =====================================================

    if looks_like_solana(token):
        print(f"🔎 Checking SOLANA: {token}")

        try:
            result = analyze_token("solana", token)
            return make_alert(result)

        except Exception as e:
            return (
                "❌ SOLANA SCAN FAILED\n\n"
                f"{type(e).__name__}: {e}"
            )

    # =====================================================
    # EVM
    # BNB + ROBINHOOD
    # =====================================================

    if looks_like_evm(token):

        results = []

        for chain in ["bnb", "robinhood"]:

            print(
                f"🔎 Checking {chain.upper()}: {token}"
            )

            try:
                result = analyze_token(chain, token)

                results.append(
                    make_alert(result)
                )

            except Exception as e:

                print(
                    f"⚠️ {chain.upper()} not found: "
                    f"{type(e).__name__}: {e}"
                )

        if results:
            return "\n\n━━━━━━━━━━━━━━━━━━\n\n".join(results)

        return (
            "❌ TOKEN NOT FOUND\n\n"
            "No usable data was found on "
            "BNB Chain or Robinhood Chain."
        )

    return (
        "❌ INVALID CONTRACT ADDRESS\n\n"
        "Please paste only the token contract address."
    )


def send_message(chat_id, text):

    url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_TOKEN}/sendMessage"
    )

    response = requests.post(
        url,
        json={
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": True,
        },
        timeout=20,
    )

    response.raise_for_status()


def main():

    print("🤖 TEMMYDEEXC BOT IS LIVE")
    print("==========================")
    print("📋 Paste contract addresses only.")
    print("🔐 READ-ONLY — NO TRADING")
    print()

    offset = None

    while True:

        try:

            response = requests.get(
                f"https://api.telegram.org/"
                f"bot{TELEGRAM_TOKEN}/getUpdates",
                params={
                    "timeout": 30,
                    "offset": offset,
                },
                timeout=40,
            )

            data = response.json()

            if not data.get("ok"):
                print("❌ Telegram error:", data)
                time.sleep(5)
                continue

            for update in data.get("result", []):

                offset = update["update_id"] + 1

                message = update.get("message", {})

                chat_id = message.get(
                    "chat", {}
                ).get("id")

                text = message.get(
                    "text",
                    ""
                ).strip()

                if not chat_id or not text:
                    continue

                # =========================================
                # START
                # =========================================

                if text == "/start":

                    send_message(
                        chat_id,
                        "🤖 TEMMYDEEXC SCANNER\n\n"
                        "✅ Online\n\n"
                        "📋 Paste a token contract address "
                        "and I will scan it automatically.\n\n"
                        "🟣 Solana\n"
                        "🟡 BNB Chain\n"
                        "🔵 Robinhood Chain\n\n"
                        "🔐 Read-only — no automatic trading."
                    )

                    print("📩 /start received")
                    continue

                # =========================================
                # IGNORE OTHER COMMANDS
                # =========================================

                if text.startswith("/"):

                    send_message(
                        chat_id,
                        "📋 Paste the contract address only."
                    )

                    continue

                print(
                    f"🔎 Contract received: {text}"
                )

                send_message(
                    chat_id,
                    "🔎 Scanning contract...\n"
                    "⏳ Checking available chains."
                )

                try:

                    result = scan_automatic(text)

                    send_message(
                        chat_id,
                        result
                    )

                    print("✅ Result sent.")

                except Exception as e:

                    error = (
                        "❌ SCAN ERROR\n\n"
                        f"{type(e).__name__}: {e}"
                    )

                    print(error)

                    send_message(
                        chat_id,
                        error
                    )

        except KeyboardInterrupt:

            print("\n🛑 Bot stopped.")
            break

        except Exception as e:

            print(
                "⚠️ Listener error:",
                type(e).__name__,
                e
            )

            time.sleep(5)


if __name__ == "__main__":
    main()
