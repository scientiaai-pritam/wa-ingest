import csv

# September folding dugi - flagged taka counts + stated meters (from WHITE.csv NOTEs,
# transcribed folding reports 30/09). meters = only where the report states them.
DEFECTS = [
 ("2026-09-10", 2, 39,  "lot 2017 39 mtr stated; lot 2018 flagged (meters not stated)"),
 ("2026-09-11", 10, "", "6 lots, per-piece meters (pieces counted)"),
 ("2026-09-12", 4, "",  "2132: 3 takas + 2133: 1"),
 ("2026-09-13", 11, "", "2208: 3, 2158: 3, 2159: 5"),
 ("2026-09-14", 36, "", "2203 ~30 pieces + 13732-TE 6"),
 ("2026-09-16", 15, "", "7 lots, many pieces (approx)"),
 ("2026-09-17", 10, "", "12217 kanra + 12218/2240/2241"),
 ("2026-09-18", 29, "", "2242/2243/2244/2307-DB"),
 ("2026-09-20", 21, "", "2288-Aastha 10 + 2341 7 + 2340 4 (approx)"),
 ("2026-09-21", 6, "",  "2150/2306/2082/2083"),
 ("2026-09-22", 17, "", "2289-Aastha 14 pcs + 2381 3"),
 ("2026-09-23", 35, "", "11 lots"),
 ("2026-09-24", 11, "", "4 lots"),
 ("2026-09-26", 30, "", "9 lots"),
 ("2026-09-27", 29, "", "11 lots"),
 ("2026-09-28", 36, 105, "7+ lots + hadding 105 mtr stated"),
 ("2026-09-29", 47, 35, "6+ lots (token counts approx, human verify) + hadding 35 mtr stated"),
 ("2026-09-30", 24, "", "5 lots + 2380 taka 47 me 3 juga"),
]

with open('data/structured/defects_september.csv', 'w', newline='', encoding='utf-8') as f:
    w = csv.writer(f)
    w.writerow(['date', 'takas_flagged', 'meters_stated', 'note'])
    w.writerows(DEFECTS)
tot_t = sum(d[1] for d in DEFECTS)
tot_m = sum(d[2] for d in DEFECTS if isinstance(d[2], int))
print(f'defects_september.csv written: {len(DEFECTS)} days, {tot_t} takas flagged, {tot_m} mtr explicitly stated (Sep total)')
