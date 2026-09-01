import os
import re
import time
import requests

# =========================================================
# TEMMYDEEXC SCANNER BOT
# SELF-CONTAINED — READ ONLY
# NO BUYING / SELLING
# =========================================================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN environment variable is missing.")

CHAINS = {
    "solana": "solana",
    "bnb": "bsc",
    "robinhood": "robinhood",
}


# =========================================================
# TELEGRAM
# =========================================================

def telegram_request(method, payload=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/{method}"

    response = requests.post(
        url,
        json=payload or {},
        timeout=40
    )

    response.raise_for_status()
    data = response.json()

    if not data.get("ok"):
        raise RuntimeError(data)

    return data


def send_message(chat_id, text):
    telegram_request(
        "sendMessage",
        {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": True,
        }
    )


# =========================================================
# ADDRESS DETECTION
# =========================================================

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


# =========================================================
# DEXSCREENER
# =========================================================

def get_pairs(chain, token):

    if chain not in CHAINS:
        raise ValueError("Unsupported chain.")

    chain_id = CHAINS[chain]

    url = (
        "https://api.dexscreener.com/"
        f"token-pairs/v1/{chain_id}/{token}"
    )

    response = requests.get(
        url,
        timeout=30
    )

    if response.status_code != 200:
        raise RuntimeError(
            f"DexScreener HTTP {response.status_code}"
        )

    data = response.json()

    if not isinstance(data, list):
        raise RuntimeError(
            "Unexpected DexScreener response."
        )

    return data


# =========================================================
# TOKEN ANALYZER
# =========================================================

def analyze_token(chain, token):

    pairs = get_pairs(chain, token)

    valid_pairs = []

    for pair in pairs:

        liquidity = (
            pair.get("liquidity", {})
            .get("usd")
        )

        if liquidity is not None:
            valid_pairs.append(pair)

    if not valid_pairs:
        raise RuntimeError(
            "No usable token or liquidity data found."
        )

    valid_pairs.sort(
        key=lambda p:
        p.get("liquidity", {}).get("usd", 0) or 0,
        reverse=True
    )

    total_liquidity = sum(
        p.get("liquidity", {}).get("usd", 0) or 0
        for p in valid_pairs
    )

    total_volume = sum(
        p.get("volume", {}).get("h24", 0) or 0
        for p in valid_pairs
    )

    buys = 0
    sells = 0

    for pair in valid_pairs:

        txns = pair.get(
            "txns",
            {}
        ).get(
            "h24",
            {}
        )

        buys += txns.get("buys", 0) or 0
        sells += txns.get("sells", 0) or 0

    trades = buys + sells

    buy_pressure = (
        buys / trades * 100
        if trades
        else 0
    )

    volume_liquidity = (
        total_volume / total_liquidity
        if total_liquidity
        else 0
    )

    strongest = valid_pairs[0]

    base_token = strongest.get(
        "baseToken",
        {}
    )

    name = base_token.get(
        "name",
        "Unknown"
    )

    symbol = base_token.get(
        "symbol",
        "Unknown"
    )

    price = strongest.get(
        "priceUsd",
        "Unknown"
    )

    # =====================================================
    # BASIC RISK SCORE
    # =====================================================

    score = 100
    flags = []

    if total_liquidity < 5000:

        score -= 35

        flags.append(
            "🔴 Very low liquidity"
        )

    elif total_liquidity < 10000:

        score -= 20

        flags.append(
            "🟠 Low liquidity"
        )

    elif total_liquidity < 50000:

        score -= 10

        flags.append(
            "🟡 Moderate liquidity"
        )

    if volume_liquidity > 30:

        score -= 20

        flags.append(
            "🟠 Extremely high volume/liquidity"
        )

    elif volume_liquidity > 10:

        score -= 10

        flags.append(
            "🟡 High volume/liquidity"
        )

    if trades:

        if buy_pressure < 45:

            score -= 20

            flags.append(
                "🔴 Strong sell pressure"
            )

        elif buy_pressure < 50:

            score -= 10

            flags.append(
                "🟠 Sell pressure"
            )

    score = max(
        0,
        min(100, score)
    )

    if score >= 80:

        rating = (
            "🟢 LOWER RISK — INVESTIGATE"
        )

    elif score >= 60:

        rating = (
            "🟡 MODERATE RISK"
        )

    elif score >= 40:

        rating = (
            "🟠 HIGH RISK"
        )

    else:

        rating = (
            "🔴 EXTREME RISK"
        )

    return {
        "chain": chain,
        "token": token,
        "name": name,
        "symbol": symbol,
        "price": price,
        "liquidity": total_liquidity,
        "volume": total_volume,
        "buys": buys,
        "sells": sells,
        "buy_pressure": buy_pressure,
        "volume_liquidity": volume_liquidity,
        "pools": len(valid_pairs),
        "score": score,
        "rating": rating,
        "flags": flags,
        "dex": strongest.get(
            "dexId",
            "Unknown"
        ),
        "url": strongest.get(
            "url",
            ""
        ),
    }


# =========================================================
# TELEGRAM ALERT
# =========================================================

def make_alert(data):

    if data["flags"]:

        risk_flags = "\n".join(
            data["flags"]
        )

    else:

        risk_flags = (
            "✅ No basic risk flags detected"
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

⚠️ This score is NOT a guarantee that a token is safe.

🔎 Research before trading.

{data["url"]}
"""


# =========================================================
# AUTOMATIC CHAIN DETECTION
# =========================================================

def scan_automatic(token):

    token = token.strip()

    # -----------------------------
    # SOLANA
    # -----------------------------

    if looks_like_solana(token):

        print(
            f"🔎 Checking SOLANA: {token}",
            flush=True
        )

        try:

            result = analyze_token(
                "solana",
                token
            )

            return make_alert(result)

        except Exception as e:

            return (
                "❌ SOLANA SCAN FAILED\n\n"
                f"{type(e).__name__}: {e}"
            )

    # -----------------------------
    # EVM
    # -----------------------------

    if looks_like_evm(token):

        results = []

        for chain in [
            "bnb",
            "robinhood"
        ]:

            print(
                f"🔎 Checking {chain.upper()}: {token}",
                flush=True
            )

            try:

                result = analyze_token(
                    chain,
                    token
                )

                results.append(
                    make_alert(result)
                )

            except Exception as e:

                print(
                    f"⚠️ {chain.upper()} not found: "
                    f"{type(e).__name__}: {e}",
                    flush=True
                )

        if results:

            return (
                "\n\n━━━━━━━━━━━━━━━━━━\n\n"
                .join(results)
            )

        return (
            "❌ TOKEN NOT FOUND\n\n"
            "No usable data was found on "
            "BNB Chain or Robinhood Chain."
        )

    return (
        "❌ INVALID CONTRACT ADDRESS\n\n"
        "Please paste only the token contract address."
    )


# =========================================================
# TELEGRAM BOT
# =========================================================

def run_bot():

    print(
        "🤖 TEMMYDEEXC BOT IS LIVE",
        flush=True
    )

    print(
        "=========================",
        flush=True
    )

    print(
        "📋 Paste a contract address only.",
        flush=True
    )

    print(
        "🔐 READ-ONLY — NO TRADING",
        flush=True
    )

    # Test token

    try:

        me = telegram_request("getMe")

        bot = me["result"]

        print(
            f"✅ Telegram connected: "
            f"{bot.get('first_name')} "
            f"@{bot.get('username')}",
            flush=True
        )

    except Exception as e:

        print(
            "❌ Telegram connection failed:",
            e,
            flush=True
        )

        return

    offset = None

    while True:

        try:

            response = requests.get(
                f"https://api.telegram.org/"
                f"bot{TELEGRAM_TOKEN}/getUpdates",
                params={
                    "timeout": 30,
                    "offset": offset
                },
                timeout=40
            )

            data = response.json()

            if not data.get("ok"):

                print(
                    "❌ Telegram error:",
                    data,
                    flush=True
                )

                time.sleep(5)

                continue

            for update in data.get(
                "result",
                []
            ):

                offset = (
                    update["update_id"] + 1
                )

                message = update.get(
                    "message",
                    {}
                )

                chat = message.get(
                    "chat",
                    {}
                )

                chat_id = chat.get(
                    "id"
                )

                text = message.get(
                    "text",
                    ""
                ).strip()

                if not chat_id or not text:
                    continue

                # -------------------------
                # COMMANDS
                # -------------------------

                if text == "/start":

                    send_message(
                        chat_id,
                        "🤖 TEMMYDEEXC SCANNER\n\n"
                        "✅ Online\n\n"
                        "📋 Paste a token contract "
                        "address only.\n\n"
                        "🟣 Solana\n"
                        "🟡 BNB\n"
                        "🔵 Robinhood\n\n"
                        "🔐 Read-only — no trading."
                    )

                    continue

                if text.startswith("/"):

                    send_message(
                        chat_id,
                        "📋 Paste the contract address only.\n\n"
                        "No command is required."
                    )

                    continue

                # -------------------------
                # SCAN
                # -------------------------

                print(
                    f"🔎 Contract received: {text}",
                    flush=True
                )

                send_message(
                    chat_id,
                    "🔎 Scanning contract...\n"
                    "⏳ Checking available chains."
                )

                try:

                    result = scan_automatic(
                        text
                    )

                    send_message(
                        chat_id,
                        result
                    )

                    print(
                        "✅ Result sent.",
                        flush=True
                    )

                except Exception as e:

                    error = (
                        "❌ SCAN ERROR\n\n"
                        f"{type(e).__name__}: {e}"
                    )

                    print(
                        error,
                        flush=True
                    )

                    send_message(
                        chat_id,
                        error
                    )

        except KeyboardInterrupt:

            print(
                "\n🛑 Bot stopped.",
                flush=True
            )

            break

        except Exception as e:

            print(
                "⚠️ Listener error:",
                type(e).__name__,
                e,
                flush=True
            )

            time.sleep(5)


# =========================================================
# START
# =========================================================

if __name__ == "__main__":
    run_bot()
