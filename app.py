from flask import Flask, render_template, request
import pandas as pd
import requests
from io import StringIO
import random
from datetime import datetime, date

app = Flask(__name__)

POWERBALL_URL = "https://raw.githubusercontent.com/akshaybapat/powerball/master/powerball.csv"
MEGAMILLIONS_URL = "https://raw.githubusercontent.com/akshaybapat/megamillions/master/megamillions.csv"

# Cache so we don't re-download every request (refresh daily)
CACHE = {
    "powerball": {"ts": None, "df": None, "main_freq": None, "special_freq": None},
    "megamillions": {"ts": None, "df": None, "main_freq": None, "special_freq": None},
}


def load_lottery_data(url: str, years: int) -> pd.DataFrame:
    """
    Loads historical lottery data from CSV URL (GitHub raw),
    filters to last N years based on 'Draw Date'.
    """
    r = requests.get(url, timeout=30)
    r.raise_for_status()

    df = pd.read_csv(StringIO(r.text))

    # Datasets use 'Draw Date'
    if "Draw Date" not in df.columns:
        raise ValueError(f"Expected 'Draw Date' column, found: {list(df.columns)}")

    df["Draw Date"] = pd.to_datetime(df["Draw Date"], errors="coerce")
    cutoff_year = datetime.now().year - years
    df = df[df["Draw Date"].dt.year >= cutoff_year].copy()

    return df


def parse_numbers(df: pd.DataFrame, special_col: str):
    """
    Parses main numbers from 'Winning Numbers' column (space-separated)
    and special ball from special_col.
    Returns frequency series for main and special numbers.
    """
    if "Winning Numbers" not in df.columns:
        raise ValueError(f"Expected 'Winning Numbers' column, found: {list(df.columns)}")
    if special_col not in df.columns:
        raise ValueError(f"Expected '{special_col}' column, found: {list(df.columns)}")

    main_nums = []
    for row in df["Winning Numbers"].dropna():
        parts = str(row).strip().split()
        # expecting 5 numbers
        for n in parts:
            main_nums.append(int(n))

    special_nums = df[special_col].dropna().astype(int)

    main_freq = pd.Series(main_nums).value_counts()
    special_freq = pd.Series(special_nums).value_counts()

    return main_freq, special_freq


def weighted_pick(freq_series: pd.Series, k: int):
    nums = freq_series.index.tolist()
    weights = freq_series.values.tolist()
    return random.choices(nums, weights=weights, k=k)


def generate_ticket(*, main_range: int, special_range: int, main_count: int,
                    weighted: bool, main_freq: pd.Series | None, special_freq: pd.Series | None):
    if weighted and main_freq is not None and special_freq is not None:
        picked = set()
        while len(picked) < main_count:
            picked.add(weighted_pick(main_freq, 1)[0])
        main_nums = sorted(picked)

        special_num = weighted_pick(special_freq, 1)[0]
        # Ensure special is within official range (safety)
        if not (1 <= int(special_num) <= special_range):
            special_num = random.randint(1, special_range)
    else:
        main_nums = sorted(random.sample(range(1, main_range + 1), main_count))
        special_num = random.randint(1, special_range)

    return main_nums, int(special_num)


def get_lottery_config(game: str):
    if game == "powerball":
        return {
            "name": "Powerball",
            "url": POWERBALL_URL,
            "special_col": "Powerball",
            "main_range": 69,
            "special_range": 26,
            "special_label": "Powerball",
        }
    elif game == "megamillions":
        return {
            "name": "Mega Millions",
            "url": MEGAMILLIONS_URL,
            "special_col": "Mega Ball",
            "main_range": 70,
            "special_range": 25,
            "special_label": "Mega Ball",
        }
    else:
        raise ValueError("Unsupported game. Use 'powerball' or 'megamillions'.")


def get_cached_freq(game: str, years: int):
    cache = CACHE[game]
    today = date.today()

    if cache["ts"] == today and cache["main_freq"] is not None and cache["special_freq"] is not None:
        return cache["main_freq"], cache["special_freq"]

    cfg = get_lottery_config(game)
    df = load_lottery_data(cfg["url"], years=years)
    main_freq, special_freq = parse_numbers(df, cfg["special_col"])

    cache["ts"] = today
    cache["df"] = df
    cache["main_freq"] = main_freq
    cache["special_freq"] = special_freq
    return main_freq, special_freq


@app.route("/", methods=["GET", "POST"])
def index():
    results = []
    error = None

    # defaults
    game = "powerball"
    years = 20
    count = 5
    mode = "weighted"

    if request.method == "POST":
        try:
            game = request.form.get("game", "powerball")
            years = int(request.form.get("years", "20"))
            count = int(request.form.get("count", "5"))
            mode = request.form.get("mode", "weighted")

            # guardrails
            years = max(1, min(years, 30))
            count = max(1, min(count, 50))

            cfg = get_lottery_config(game)
            weighted = (mode == "weighted")

            main_freq, special_freq = (None, None)
            if weighted:
                main_freq, special_freq = get_cached_freq(game, years)

            for _ in range(count):
                main_nums, special_num = generate_ticket(
                    main_range=cfg["main_range"],
                    special_range=cfg["special_range"],
                    main_count=5,
                    weighted=weighted,
                    main_freq=main_freq,
                    special_freq=special_freq,
                )
                results.append({"main": main_nums, "special": special_num})

        except Exception as e:
            error = str(e)

    return render_template(
        "index.html",
        results=results,
        error=error,
        game=game,
        years=years,
        count=count,
        mode=mode,
    )


@app.route("/api/generate")
def api_generate():
    game = request.args.get("game", "powerball")
    years = int(request.args.get("years", "20"))
    count = int(request.args.get("count", "5"))
    mode = request.args.get("mode", "weighted")

    years = max(1, min(years, 30))
    count = max(1, min(count, 50))

    cfg = get_lottery_config(game)
    weighted = (mode == "weighted")

    main_freq, special_freq = (None, None)
    if weighted:
        main_freq, special_freq = get_cached_freq(game, years)

    out = []
    for _ in range(count):
        main_nums, special_num = generate_ticket(
            main_range=cfg["main_range"],
            special_range=cfg["special_range"],
            main_count=5,
            weighted=weighted,
            main_freq=main_freq,
            special_freq=special_freq,
        )
        out.append({"numbers": main_nums, cfg["special_label"]: special_num})

    return {"game": cfg["name"], "years": years, "mode": mode, "tickets": out}


if __name__ == "__main__":
    # 0.0.0.0 lets LAN devices access it (same Wi-Fi)
    app.run(host="0.0.0.0", port=5000, debug=True)