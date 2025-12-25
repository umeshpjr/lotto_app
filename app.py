from flask import Flask, render_template, request
import pandas as pd
import requests
from io import StringIO
import random
from datetime import datetime

app = Flask(__name__)

POWERBALL_URL = "https://www.powerball.com/api/v1/numbers/powerball?_format=csv"
MEGAMILLIONS_URL = "https://www.megamillions.com/api/v1/numbers/megaball?_format=csv"

# Cache so we don't re-download every request
CACHE = {
    "powerball": {"ts": None, "df": None, "main_freq": None, "special_freq": None},
    "megamillions": {"ts": None, "df": None, "main_freq": None, "special_freq": None},
}

def load_lottery_data(url: str, years: int) -> pd.DataFrame:
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    df = pd.read_csv(StringIO(r.text))

    df["draw_date"] = pd.to_datetime(df["draw_date"], errors="coerce")
    cutoff_year = datetime.now().year - years
    df = df[df["draw_date"].dt.year >= cutoff_year].copy()
    return df

def extract_frequencies(df: pd.DataFrame, main_cols: list[str], special_col: str):
    main_numbers = df[main_cols].values.flatten()
    special_numbers = df[special_col].values
    main_freq = pd.Series(main_numbers).value_counts().sort_index()
    special_freq = pd.Series(special_numbers).value_counts().sort_index()
    return main_freq, special_freq

def weighted_pick(freq_series: pd.Series, k: int):
    nums = freq_series.index.tolist()
    weights = freq_series.values.tolist()
    return random.choices(nums, weights=weights, k=k)

def generate_ticket(*, main_range: int, special_range: int, main_count: int,
                    weighted: bool, main_freq: pd.Series | None, special_freq: pd.Series | None):
    if weighted and main_freq is not None and special_freq is not None:
        # Ensure uniqueness in main numbers
        picked = set()
        while len(picked) < main_count:
            picked.add(weighted_pick(main_freq, 1)[0])
        main_nums = sorted(picked)
        special_num = weighted_pick(special_freq, 1)[0]
    else:
        main_nums = sorted(random.sample(range(1, main_range + 1), main_count))
        special_num = random.randint(1, special_range)

    return main_nums, special_num

def get_lottery_config(game: str):
    if game == "powerball":
        return {
            "name": "Powerball",
            "url": POWERBALL_URL,
            "main_cols": ["number_1","number_2","number_3","number_4","number_5"],
            "special_col": "powerball",
            "main_range": 69,
            "special_range": 26,
            "special_label": "Powerball",
        }
    elif game == "megamillions":
        return {
            "name": "Mega Millions",
            "url": MEGAMILLIONS_URL,
            "main_cols": ["number_1","number_2","number_3","number_4","number_5"],
            "special_col": "mega_ball",
            "main_range": 70,
            "special_range": 25,
            "special_label": "Mega Ball",
        }
    else:
        raise ValueError("Unsupported game")

def get_cached_freq(game: str, years: int):
    # Refresh cache once per day (you can change this)
    cache = CACHE[game]
    today = datetime.now().date()

    if cache["ts"] == today and cache["main_freq"] is not None:
        return cache["main_freq"], cache["special_freq"]

    cfg = get_lottery_config(game)
    df = load_lottery_data(cfg["url"], years=years)
    main_freq, special_freq = extract_frequencies(df, cfg["main_cols"], cfg["special_col"])

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
                results.append({
                    "main": main_nums,
                    "special": special_num,
                })

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

# Simple JSON endpoint (handy for mobile shortcuts / automation)
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
    # 0.0.0.0 lets your phone access it on same Wi-Fi
    app.run(host="0.0.0.0", port=5000, debug=True)

