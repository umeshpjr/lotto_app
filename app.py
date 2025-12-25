from flask import Flask, render_template, request
import pandas as pd
import random
from datetime import datetime, date
from pathlib import Path

app = Flask(__name__)

BASE_DIR = Path(__file__).resolve().parent
POWERBALL_CSV = BASE_DIR / "powerball.csv"
MEGAMILLIONS_CSV = BASE_DIR / "megamillions.csv"

CACHE = {
    "powerball": {"ts": None, "main_freq": None, "special_freq": None},
    "megamillions": {"ts": None, "main_freq": None, "special_freq": None},
}

# Your CSV layout (NO HEADER):
# Col A: ignore
# Col B..J: month, day, year, n1..n5, special
BASE_COLS = ["IGNORED", "Month", "Day", "Year", "N1", "N2", "N3", "N4", "N5", "Special"]


def load_lottery_data(csv_path: Path, years: int) -> pd.DataFrame:
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV not found: {csv_path}")

    df = pd.read_csv(csv_path, header=None, names=BASE_COLS)

    # Build Draw Date from Month/Day/Year
    df["Draw Date"] = pd.to_datetime(
        dict(year=df["Year"], month=df["Month"], day=df["Day"]),
        errors="coerce"
    )

    cutoff_year = datetime.now().year - years
    df = df[df["Draw Date"].dt.year >= cutoff_year].copy()

    # Ensure numeric
    for c in ["N1", "N2", "N3", "N4", "N5", "Special"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    df = df.dropna(subset=["N1", "N2", "N3", "N4", "N5", "Special", "Draw Date"])

    return df


def build_frequencies(df: pd.DataFrame):
    main_nums = df[["N1", "N2", "N3", "N4", "N5"]].astype(int).values.flatten()
    special_nums = df["Special"].astype(int).values

    main_freq = pd.Series(main_nums).value_counts()
    special_freq = pd.Series(special_nums).value_counts()

    return main_freq, special_freq


def weighted_pick(freq_series: pd.Series, k: int):
    nums = freq_series.index.tolist()
    weights = freq_series.values.tolist()
    return random.choices(nums, weights=weights, k=k)


def generate_ticket(main_range: int, special_range: int, weighted: bool,
                    main_freq: pd.Series | None, special_freq: pd.Series | None):
    if weighted and main_freq is not None and special_freq is not None:
        picked = set()
        while len(picked) < 5:
            picked.add(weighted_pick(main_freq, 1)[0])
        main_nums = sorted(int(x) for x in picked)

        special = int(weighted_pick(special_freq, 1)[0])
        if not (1 <= special <= special_range):
            special = random.randint(1, special_range)
    else:
        main_nums = sorted(random.sample(range(1, main_range + 1), 5))
        special = random.randint(1, special_range)

    return main_nums, special


def get_config(game: str):
    if game == "powerball":
        return {
            "name": "Powerball",
            "csv": POWERBALL_CSV,
            "main_range": 69,
            "special_range": 26,
            "special_label": "Powerball",
        }
    elif game == "megamillions":
        return {
            "name": "Mega Millions",
            "csv": MEGAMILLIONS_CSV,
            "main_range": 70,
            "special_range": 25,
            "special_label": "Mega Ball",
        }
    else:
        raise ValueError("Unsupported game. Use 'powerball' or 'megamillions'.")


def get_cached_freq(game: str, years: int):
    cache = CACHE[game]
    today = date.today()

    if cache["ts"] == today and cache["main_freq"] is not None:
        return cache["main_freq"], cache["special_freq"]

    cfg = get_config(game)
    df = load_lottery_data(cfg["csv"], years=years)
    main_freq, special_freq = build_frequencies(df)

    cache["ts"] = today
    cache["main_freq"] = main_freq
    cache["special_freq"] = special_freq
    return main_freq, special_freq


@app.route("/", methods=["GET", "POST"])
def index():
    results = []
    error = None

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

            years = max(1, min(years, 30))
            count = max(1, min(count, 50))

            cfg = get_config(game)
            weighted = (mode == "weighted")

            main_freq, special_freq = (None, None)
            if weighted:
                main_freq, special_freq = get_cached_freq(game, years)

            for _ in range(count):
                main_nums, special_num = generate_ticket(
                    main_range=cfg["main_range"],
                    special_range=cfg["special_range"],
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
        mode=mode
    )


@app.route("/api/generate")
def api_generate():
    game = request.args.get("game", "powerball")
    years = int(request.args.get("years", "20"))
    count = int(request.args.get("count", "5"))
    mode = request.args.get("mode", "weighted")

    years = max(1, min(years, 30))
    count = max(1, min(count, 50))

    cfg = get_config(game)
    weighted = (mode == "weighted")

    main_freq, special_freq = (None, None)
    if weighted:
        main_freq, special_freq = get_cached_freq(game, years)

    tickets = []
    for _ in range(count):
        main_nums, special_num = generate_ticket(
            main_range=cfg["main_range"],
            special_range=cfg["special_range"],
            weighted=weighted,
            main_freq=main_freq,
            special_freq=special_freq,
        )
        tickets.append({"numbers": main_nums, cfg["special_label"]: special_num})

    return {"game": cfg["name"], "years": years, "mode": mode, "tickets": tickets}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
