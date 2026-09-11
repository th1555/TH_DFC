# Running the Transfermarkt probes in PyCharm

Two scripts:
- **`tm_probe.py`** — checks the squad page (name, age, position, market value)
- **`tm_probe_minutes.py`** — checks the performance page (appearances, goals, assists, **minutes**)

Run them on your own machine (home network). Transfermarkt blocks cloud/VPN IPs, so a cloud sandbox can't reach it — your laptop can.

---

## 0. One-time prerequisites

- **Python 3.10+** — check by opening a terminal and running `python3 --version` (macOS/Linux) or `python --version` (Windows). If missing, install from python.org.
- **PyCharm** — the free **Community Edition** is fine (jetbrains.com/pycharm/download).

---

## 1. Create the project

1. Open PyCharm → **New Project**.
2. Set a location, e.g. `~/dumbarton-recruitment`.
3. Under the Python interpreter option, choose **New environment using Virtualenv** (PyCharm ticks this by default). This gives the project its own clean, isolated Python — exactly what you want.
4. Click **Create**.

---

## 2. Add the two scripts

1. Drag `tm_probe.py` and `tm_probe_minutes.py` into the project window (or copy them into the project folder on disk, then they'll appear in PyCharm's file tree on the left).
2. Confirm you can see both in the **Project** panel on the left.

---

## 3. Install the dependencies

Easiest way — use PyCharm's built-in terminal (it auto-activates the project's virtualenv):

1. Open the terminal at the bottom of PyCharm: **View → Tool Windows → Terminal** (or the "Terminal" tab at the bottom).
2. You should see the environment name in parentheses at the start of the prompt, e.g. `(venv)`. That means the virtualenv is active.
3. Run:
   ```
   pip install requests beautifulsoup4 lxml pandas
   ```
4. Wait for "Successfully installed …".

*(Alternative GUI route: **Settings → Project → Python Interpreter → the `+` button**, then search and install each of `requests`, `beautifulsoup4`, `lxml`, `pandas`.)*

---

## 4. Run the first probe

1. Open `tm_probe.py`.
2. Click the green **▶ Run** arrow at the top right (or right-click in the editor → **Run 'tm_probe'**).
3. Output appears in the **Run** panel at the bottom.

**What good output looks like** — for each league: a club count, a sample club with a player count, and an `OK / MISSING` line per field:
```
=== Scottish League Two  (SC4) ===
  clubs found: 10
  sample club: Dumbarton  ->  24 players parsed
  field availability on squad page:
    OK   name
    OK   position
    OK   age/dob
    OK   market_value
```

---

## 5. Run the second probe

1. Open `tm_probe_minutes.py`.
2. Green **▶ Run** arrow again.
3. The line that matters most is the `minutes` one — it's the field most likely to be missing at lower tiers, and it's the denominator for every per-90 metric:
```
=== Scottish League Two  (SC4)  season 2025/26 ===
  sample player: ...  (id ...)
  performance-page field availability:
    OK   appearances
    OK   goals
    OK   assists
    OK   minutes        <-- if this says MISSING, that league falls back to per-appearance rates
```

---

## 6. Reading the result (your go / no-go)

- **SPFL tiers (SC1–SC4) all parse with minutes present** → green light for the core pool.
- **Highland / Lowland don't parse** → those feeder leagues aren't cleanly on TM; the coverage edge narrows and you lean harder on free agents + released lists.
- **Minutes MISSING for a tier** → usable, but those players compare only on cruder per-appearance rates and should be flagged lower-confidence in the model.

---

## 7. Adding the feeder leagues

To test Highland/Lowland, find their Transfermarkt competition codes (browse to the league on transfermarkt.com and read the code from the URL, the bit after `/wettbewerb/`), then edit the `LEAGUES` dict at the top of **both** scripts:
```python
LEAGUES = {
    "Scottish League Two":  "SC4",
    "Highland League":      "XXXX",   # <- paste the real code
    "Lowland League":       "YYYY",
}
```

---

## 8. Troubleshooting

- **Every league shows `403`** → Transfermarkt is blocking your IP. Run from a normal home connection (not a VPN/office proxy), and increase `DELAY` at the top of the script from `4.0` to `8.0` or more.
- **`ModuleNotFoundError`** → the dependencies didn't install into the project's venv. Re-check step 3, making sure the terminal prompt shows `(venv)` before running `pip install`.
- **`clubs found: 0` or parse errors** → Transfermarkt changed its page structure (it happens). The CSS selectors in the script would need a small update — worth a note, not a crisis.
- **Be polite:** keep the delay in, don't hammer the site, cache anything you pull for real. This is a spike, not the ingestion pipeline.

---

## Note on the real pipeline

These probes are a feasibility check, not the data layer. For an actual pipeline, prefer **`worldfootballR`** (R, mature Transfermarkt support) or the maintained **`transfermarkt-datasets`** project over hand-scraping — sturdier and less likely to break when TM changes its HTML.
