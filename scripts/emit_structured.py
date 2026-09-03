"""Emit structured CSVs for the OCR'd grey-inward sheets and order 3644.

Outputs under data/structured/:
  grey_inward_lines.csv    - one row per party/quality line item
  grey_inward_sheets.csv   - one row per sheet/day with section subtotals + TOH
  order_3644_colorways.csv - colorway allocation from the print order sheet
"""
import csv
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data" / "structured"

# (sheet_date, section, party, quality, taka, confidence)
LINES = [
    # 2026-08-20, TOH 3469
    ("2026-08-20", "Jafar", "Tex Styles", "wely", 80, "med"),
    ("2026-08-20", "Jafar", "Agile Expr", "Ranjeli", 400, "med"),
    ("2026-08-20", "Jafar", "Meena cm", "PC TP 800", 76, "med"),
    ("2026-08-20", "Jafar", "SK tex", "Moss Slub", 72, "med"),
    ("2026-08-20", "Jafar", "Samunit Ex", "wely", 284, "low"),
    ("2026-08-20", "Jafar", "D.c. crea", "Ranjeli + wely", 200, "med"),
    ("2026-08-20", "Jafar", "Diwan Intex", "wely", 48, "high"),
    ("2026-08-20", "Jafar", "V.Tex ove", "PC TP 1200", 467, "med"),
    ("2026-08-20", "Jafar", "Shakti Ex", "TP 1200", 25, "med"),
    ("2026-08-20", "Sunil", "BS Export", "Bossio", 39, "med"),
    ("2026-08-20", "Sunil", "Agile Expr", "Bossio", 30, "med"),
    ("2026-08-20", "Sunil", "Vijay Laxmi", "Alpine LR", 144, "med"),
    ("2026-08-20", "Rakesh", "Ravi Tex sur", "wely", 336, "med"),
    ("2026-08-20", "Rakesh", "Prachi Sury", "PC TP 800 slub", 240, "med"),
    ("2026-08-20", "Rakesh", "VK Print", "PC TP 800 slub", 48, "med"),
    ("2026-08-20", "Rakesh", "R. Monutexal", "PC TP 800 slub", 96, "low"),
    ("2026-08-20", "Rakesh", "Tiga craj", "PC TP 800 slub", 96, "low"),
    ("2026-08-20", "Rakesh", "MAHIMA Fab", "PC TP 800 slub", 432, "med"),
    ("2026-08-20", "Rakesh", "Mishri cloth", "TP 1200 slub", 96, "med"),
    ("2026-08-20", "Digital", "Rajkumar tex", "wely", 140, "high"),
    ("2026-08-20", "Digital", "RS Export", "wely", 120, "high"),
    # 2026-08-21, TOH 2233
    ("2026-08-21", "Jafar", "Vinayak Print", "wely", 99, "med"),
    ("2026-08-21", "Jafar", "Bhagwati fab", "wely", 186, "med"),
    ("2026-08-21", "Jafar", "V.Tex ove", "PC TP 800 slub", 156, "med"),
    ("2026-08-21", "Jafar", "Krishna Fab", "satin grey", 53, "med"),
    ("2026-08-21", "Jafar", "A I Sawa tex", "TP 1200 slub", 39, "low"),
    ("2026-08-21", "Sunil", "F. tex", "wely", 57, "med"),
    ("2026-08-21", "Sunil", "BS Export", "Bossio", 24, "med"),
    ("2026-08-21", "Sunil", "Raghav cm", "Bossio", 138, "med"),
    ("2026-08-21", "Sunil", "Bhai Bhai", "TP 1200 slub", 32, "med"),
    ("2026-08-21", "Sunil", "Asian tex", "", 58, "memo"),  # side memo on pad, NOT counted in Sunil's 251
    ("2026-08-21", "Rakesh", "Karni Kripa", "wely", 111, "med"),
    ("2026-08-21", "Rakesh", "Mishri cloth", "Dulmes Bossio", 360, "med"),
    ("2026-08-21", "Rakesh", "Shree Radhekrishna", "wely", 48, "med"),
    ("2026-08-21", "Rakesh", "Brij I", "TP 1200 slub", 48, "low"),
    ("2026-08-21", "Rakesh", "VANITA Sur", "TP 800 slub", 96, "med"),
    ("2026-08-21", "Rakesh", "Prachi Sury", "PC TP 800 slub", 384, "med"),
    ("2026-08-21", "Rakesh", "Shree Siddhivinayak", "TP 1200", 48, "med"),
    ("2026-08-21", "Rakesh", "MAHIMA Fab", "PC TP 800 slub", 216, "med"),
    ("2026-08-21", "Digital", "Silver ove", "wely", 100, "med"),
    ("2026-08-21", "Digital", "Globle cm", "TP 1200 slub", 38, "med"),
    # 2026-08-22, TOH 2561
    ("2026-08-22", "Jafar", "NIRVANA Exp", "chiffon", 532, "med"),
    ("2026-08-22", "Jafar", "V. TEX ove", "PC 600 TP slub", 156, "med"),
    ("2026-08-22", "Jafar", "KK. Intexnal", "PC 600 TP slub", 122, "med"),
    ("2026-08-22", "Jafar", "SUNAKUI cm", "satin grey", 48, "low"),
    ("2026-08-22", "Sunil", "BS Export", "Alpine LR", 133, "med"),  # corrected figure on sheet
    ("2026-08-22", "Sunil", "D.c. cream", "wely", 50, "med"),
    ("2026-08-22", "Sunil", "Rajkumar tex", "Bossio", 25, "med"),
    ("2026-08-22", "Sunil", "Raghav cm", "Bossio", 130, "med"),
    ("2026-08-22", "Sunil", "Vidhasi fab", "Bossio", 33, "low"),
    ("2026-08-22", "Sunil", "MAHA DEVI Ent", "TP 800 slub", 48, "med"),
    ("2026-08-22", "Rakesh", "Darpan print", "Dulmoss", 48, "med"),
    ("2026-08-22", "Rakesh", "MAHIMA Fab", "STAR LITE + TP 1200", 288, "med"),  # 216+72
    ("2026-08-22", "Rakesh", "Mishri cloth", "TP 1200 slub", 360, "med"),
    ("2026-08-22", "Rakesh", "Suree Karni Kripa", "TP 800 slub", 168, "med"),
    ("2026-08-22", "Rakesh", "Prachi Sury", "TP 800 slub", 96, "med"),
    ("2026-08-22", "Digital", "Shree SAY Tex", "satin grey + cream", 136, "med"),
    ("2026-08-22", "Digital", "SUNRISE", "30x30 TP + wely", 188, "med"),
    # 2026-08-23, TOH 891
    ("2026-08-23", "Jafar", "Diwan Intex", "wely", 100, "high"),
    ("2026-08-23", "Jafar", "Agile Expr", "Ranjeli", 60, "high"),
    ("2026-08-23", "Jafar", "Mateshwar", "PC TP 800", 154, "med"),
    ("2026-08-23", "Sunil", "Diwan Intex", "wely", 98, "high"),
    ("2026-08-23", "Sunil", "Rajkumar tex", "dyed safin gut", 146, "low"),
    ("2026-08-23", "Sunil", "Kanhaiya tex", "Bossio strip", 148, "med"),
    ("2026-08-23", "Sunil", "Rachna Tex", "Alpine", 36, "med"),
    ("2026-08-23", "Sunil", "Bhai Bhai cm", "TP 1200 grey slub", 129, "med"),
    ("2026-08-23", "Digital", "Rajkumar tex", "wely", 20, "high"),
    # 2026-08-24, TOH 3356
    ("2026-08-24", "Jafar", "Agile Expr", "NXC SRN", 120, "med"),
    ("2026-08-24", "Jafar", "K.K. Int", "PC TP slub", 60, "med"),
    ("2026-08-24", "Jafar", "A I Sng tex", "TP grey slub", 42, "med"),
    ("2026-08-24", "Sunil", "Saffron Ex", "Alpine", 651, "med"),
    ("2026-08-24", "Sunil", "Raghav cm", "Moss Bossio", 68, "med"),
    ("2026-08-24", "Rakesh", "Shree Guru Kirpa", "TP 1200 grey", 96, "med"),
    ("2026-08-24", "Rakesh", "Prachi Saree", "TP 800 grey slub", 264, "med"),
    ("2026-08-24", "Rakesh", "Shree Bade Baba", "moss slub wely grey", 96, "low"),  # quality struck on pad
    ("2026-08-24", "Rakesh", "Mishri cloth", "TP 1200 grey", 144, "med"),
    ("2026-08-24", "Rakesh", "MAHIMA Fab", "Bossio", 768, "med"),  # handwritten 780/788; 768 makes R=1900 exact
    ("2026-08-24", "Rakesh", "VK. Print", "TP 800 grey slub", 96, "med"),
    ("2026-08-24", "Rakesh", "RAVI Ray", "wely", 216, "med"),
    ("2026-08-24", "Rakesh", "Shree Siddhivinayak", "wely", 96, "med"),
    ("2026-08-24", "Rakesh", "Karni Kripa", "TP 800 grey slub", 124, "med"),
    ("2026-08-24", "Digital", "MAHIMA Fab", "wely", 240, "high"),
    ("2026-08-24", "Digital", "Agile Expr", "Tissue georgette", 200, "med"),
    ("2026-08-24", "Digital", "TATER Expr", "Georgette", 25, "med"),
    ("2026-08-24", "Digital", "TATER Expr", "TP 1200 grey Sena Colour", 50, "low"),  # ditto mark
    # 2026-08-25, TOH 2786
    ("2026-08-25", "Jafar", "TEX Styles", "wely", 175, "med"),
    ("2026-08-25", "Jafar", "ARPITA Ex", "TP 1200 grey", 100, "med"),
    ("2026-08-25", "Jafar", "MATESWari", "PC 800 TP", 154, "med"),
    ("2026-08-25", "Jafar", "V. TEX cm", "PC 800 TP slub", 156, "med"),
    ("2026-08-25", "Jafar", "K.K. Int", "PC 900 TP slub", 171, "med"),
    ("2026-08-25", "Jafar", "NAVAL cm", "TP moss grey", 48, "med"),
    ("2026-08-25", "Jafar", "MARF. Ex", "TP moss grey", 268, "med"),
    ("2026-08-25", "Sunil", "BS Export", "Alpine LR", 32, "med"),
    ("2026-08-25", "Sunil", "TIRANG Fab", "Alpine LR", 144, "med"),
    ("2026-08-25", "Sunil", "MARF. Export", "wely", 223, "med"),
    ("2026-08-25", "Sunil", "GL. Texex", "TP grey", 2, "memo"),  # figure unclear, not counted (S=399 = first 3 rows)
    ("2026-08-25", "Rakesh", "Tiga cm", "MAYURI", 144, "med"),
    ("2026-08-25", "Rakesh", "RAVI Ray sang", "wely", 384, "med"),
    ("2026-08-25", "Rakesh", "MAHIMA Fab", "TP 800 grey", 336, "med"),
    ("2026-08-25", "Rakesh", "BM. Tex", "TP 800 grey slub", 72, "med"),
    ("2026-08-25", "Rakesh", "VK. Print", "TP 800 grey slub", 48, "med"),
    ("2026-08-25", "Rakesh", "Shree Guru Kirpa", "TP grey", 96, "med"),
    ("2026-08-25", "Rakesh", "Mishri cloth", "TP grey slub", 96, "med"),
    ("2026-08-25", "Digital", "RS. Expr", "wet los + sequins", 107, "med"),
    ("2026-08-25", "Digital", "TEX Styles", "Leon", 32, "med"),
    # 2026-08-26, TOH 1514
    ("2026-08-26", "Jafar", "Agile Expr", "Ranjeli", 310, "med"),
    ("2026-08-26", "Jafar", "Shiv Shakti Print", "NXC SRN", 257, "med"),
    ("2026-08-26", "Jafar", "ARPITA Int", "TP moss grey", 100, "med"),
    ("2026-08-26", "Jafar", "A I Sng tex", "TP grey slub", 81, "med"),
    ("2026-08-26", "Jafar", "K.K. Int", "PC TP 900 slub", 57, "med"),
    ("2026-08-26", "Jafar", "MEERA. Impex", "TP moss grey slub", 13, "med"),
    ("2026-08-26", "Jafar", "TEX Style", "TP moss grey", 40, "med"),
    ("2026-08-26", "Sunil", "Agile Expr", "Bossio", 13, "med"),
    ("2026-08-26", "Sunil", "Ruhani Int", "Bossio", 100, "med"),
    ("2026-08-26", "Sunil", "Diwan Bro", "wely 40 + Alpine cherry 41", 81, "med"),
    ("2026-08-26", "Sunil", "RajKamal tex", "Bossio", 47, "med"),
    ("2026-08-26", "Sunil", "Parmi Fab", "TP grey slub", 12, "med"),
    ("2026-08-26", "Rakesh", "Diwan Bro", "wely", 190, "med"),
    ("2026-08-26", "Rakesh", "MAHIMA Fab", "TP 800 grey slub", 72, "med"),
    ("2026-08-26", "Rakesh", "BRIJ I", "TP 800 grey", 48, "med"),
    ("2026-08-26", "Rakesh", "VK. Print", "TP moss grey", 48, "med"),
    ("2026-08-26", "Digital", "RajKamal tex", "organz strip", 45, "med"),
    # 2026-08-27, TOH 2470
    ("2026-08-27", "Jafar", "VN. Style", "wely", 100, "low"),  # 180 struck, 100 written
    ("2026-08-27", "Jafar", "Diwan Int", "wely", 98, "med"),
    ("2026-08-27", "Jafar", "V. TEX cm", "PC TP moss grey", 156, "med"),
    ("2026-08-27", "Jafar", "K.K. Int", "PC TP 300 moss grey", 57, "med"),
    ("2026-08-27", "Jafar", "A I Sng tex", "TP grey slub", 40, "med"),
    ("2026-08-27", "Sunil", "BS. Export", "Alpine LR", 36, "med"),
    ("2026-08-27", "Sunil", "Agile Expr", "Alpine LR", 175, "med"),
    ("2026-08-27", "Sunil", "VN. Style", "Ranjeli", 200, "med"),
    ("2026-08-27", "Sunil", "Bela. Fabric", "Bossio", 155, "med"),
    ("2026-08-27", "Sunil", "Diwan Impex", "wely", 50, "med"),
    ("2026-08-27", "Sunil", "Raghav cm", "Bossio + TP moss grey", "174+48", "low"),  # rows sum 1152 vs S=1052; Raghav may be 74
    ("2026-08-27", "Sunil", "MUNesh tex", "TP moss grey slub", 143, "med"),
    ("2026-08-27", "Sunil", "TATER Expr", "TP moss grey slub", 75, "med"),
    ("2026-08-27", "Sunil", "SIA. Fabric", "TP moss grey", 96, "med"),
    ("2026-08-27", "Rakesh", "Prachi sar", "TP 800 grey slub", 336, "med"),
    ("2026-08-27", "Rakesh", "Vanita sar", "TP 800 grey", 96, "med"),
    ("2026-08-27", "Rakesh", "Shree KV. Fab", "TP moss grey", 312, "med"),
    ("2026-08-27", "Rakesh", "Shree Bade BABA", "TP moss grey slub", 96, "med"),
    ("2026-08-27", "Rakesh", "BN. tex", "60 gm", 72, "med"),
    ("2026-08-27", "Digital", "AL Barkat", "Brescia", 33, "med"),
    ("2026-08-27", "Digital", "SHANTI Expr", "TP moss grey", 22, "med"),
    # 2026-08-29, TOH 1447 (heavy corrections on pad; TOH box struck, 1447 circled)
    ("2026-08-29", "Jafar", "Agile Expr", "wet pe + Rangoli", 153, "med"),
    ("2026-08-29", "Jafar", "Parshvam. Fab", "Pinless stripe", 198, "low"),
    ("2026-08-29", "Jafar", "V. TEX cm", "PC TP 1600 / 20 Party", 312, "med"),
    ("2026-08-29", "Jafar", "Bhagu Fab", "TP moss grey", 34, "med"),
    ("2026-08-29", "Jafar", "Meena cm", "PC EMD 1212 loose", 230, "med"),
    ("2026-08-29", "Sunil", "K. VEE. Export", "Bossio", 30, "med"),
    ("2026-08-29", "Sunil", "Kanhaiya Fab", "Bossio", 30, "med"),
    ("2026-08-29", "Sunil", "MAHADEVI Ent", "TP moss grey slub", 96, "med"),
    ("2026-08-29", "Sunil", "STYLIST. Fab", "TP moss grey", 76, "med"),
    ("2026-08-29", "Rakesh", "RV. Fab", "wely", 96, "med"),
    ("2026-08-29", "Rakesh", "Shree Bade BABA", "TP moss grey slub", 96, "med"),
    ("2026-08-29", "Rakesh", "Prachi sar", "TP moss grey", 96, "med"),
    # 2026-08-30, TOH 762 (28/8 sheet never posted; 29/8 = 1447)
    ("2026-08-30", "Jafar", "AL Barkat", "30x32", 72, "med"),
    ("2026-08-30", "Jafar", "SUNSHINE Int", "Golden ox ford", 20, "low"),
    ("2026-08-30", "Jafar", "Vinayak print", "wely", 100, "med"),
    ("2026-08-30", "Jafar", "V. TEX cm", "PC TP 800/1200 grey slub", 155, "med"),
    ("2026-08-30", "Sunil", "Viddharth Ex", "Bossio", 104, "med"),
    ("2026-08-30", "Sunil", "RajKamal tex", "Satin-cut + Bossio", 75, "med"),
    ("2026-08-30", "Sunil", "Siddharth Fab", "Bossio + TP moss grey slub", 196, "med"),
    ("2026-08-30", "Digital", "RajKamal tex", "30x30 visc teryl", 40, "med"),
    # 2026-08-31, TOH 1255
    ("2026-08-31", "Jafar", "ARPITA Int", "Ranjeli", 100, "med"),
    ("2026-08-31", "Jafar", "A I Sng tex", "Almas", 90, "med"),
    ("2026-08-31", "Jafar", "MEERA. Impex", "TP moss grey slub", 14, "med"),
    ("2026-08-31", "Sunil", "VN. Style", "TP moss grey", 250, "med"),
    ("2026-08-31", "Sunil", "TATER Expr", "TP grey", 75, "med"),
    ("2026-08-31", "Sunil", "SIA. Fabric", "TP grey slub", 96, "med"),
    ("2026-08-31", "Sunil", "GL. tex", "TP grey slub", 90, "med"),
    ("2026-08-31", "Sunil", "MUNesh tex", "TP grey slub", 60, "med"),
    ("2026-08-31", "Rakesh", "Mishri cloth", "TP moss grey", 72, "med"),
    ("2026-08-31", "Rakesh", "Shree Krishna tex", "TP moss grey", 360, "med"),
    ("2026-08-31", "Rakesh", "Prachi Sar", "TP moss grey", 48, "med"),
    # 2026-09-01, TOH 2351
    ("2026-09-01", "Jafar", "Agile Expr", "20x20 + TP", 350, "med"),
    ("2026-09-01", "Jafar", "MARF. Expr", "Ranjeli", 114, "med"),
    ("2026-09-01", "Jafar", "FINE THREAD", "wely grey", 203, "med"),
    ("2026-09-01", "Jafar", "SHIVSHAKTI tex", "Half panam + NXC grey", 207, "med"),
    ("2026-09-01", "Sunil", "F. Tex", "wett sequins", 117, "med"),
    ("2026-09-01", "Sunil", "Diwan Impex", "wely", 97, "med"),
    ("2026-09-01", "Sunil", "Raghav cm", "Bossio", 264, "med"),
    ("2026-09-01", "Sunil", "Ruhani Fab", "Bossio", 50, "med"),
    ("2026-09-01", "Sunil", "Shree Munnilal", "Bossio", 60, "med"),
    ("2026-09-01", "Sunil", "VN. Style", "Bossio + Ranjeli + TP grey slub", "150+47", "med"),
    ("2026-09-01", "Rakesh", "Mishri clothing", "TP moss grey", 216, "med"),
    ("2026-09-01", "Rakesh", "Mishri clothing", "white", 96, "low"),  # rows sum 408 vs R=406 (-2)
    ("2026-09-01", "Rakesh", "Shree RV. Fab", "TP moss grey", 48, "med"),
    ("2026-09-01", "Rakesh", "SUMITINath", "TP moss grey", 48, "med"),
    ("2026-09-01", "Digital", "Aastha tex", "wely", 112, "med"),
    ("2026-09-01", "Digital", "Globle Fab", "Kasturi white", 90, "med"),
    ("2026-09-01", "Digital", "RajKamal tex", "Gold jali print", 60, "med"),
    ("2026-09-01", "Digital", "Mukesh tex", "viscose white", 13, "low"),  # D rows sum 275 vs 286 (-11)
]

# (sheet_date, jafar, sunil, rakesh, digital, toh, note)
SHEETS = [
    ("2026-08-20", 1652, 213, 1344, 260, 3469,
     "all sections exact (human-verified: Shakti Ex 25, Agile Expr 30)"),
    ("2026-08-21", 533, 251, 1311, 138, 2233,
     "all sections exact ('Asian tex 58' is a side memo, not counted)"),
    ("2026-08-22", 858, 419, 960, 324, 2561, "all sections exact"),
    ("2026-08-23", 314, 557, 0, 20, 891, "all sections exact (human-verified: Kanhaiya tex 148)"),
    ("2026-08-24", 222, 719, 1900, 515, 3356, "all sections exact"),
    ("2026-08-25", 1072, 399, 1176, 139, 2786, "all sections exact (GL. Texex side memo excluded)"),
    ("2026-08-26", 858, 253, 358, 45, 1514, "all sections exact"),
    ("2026-08-27", 451, 1052, 912, 55, 2470, "J/R/D exact; Sunil rows sum 1152 (+100, Raghav 174 vs 74 unclear)"),
    ("2026-08-28", None, None, None, None, None, "sheet not yet received/posted"),
    ("2026-08-29", 927, 232, 288, 0, 1447,
     "J/R/D exact (human-verified: Kanhaiya Fab 30); Digital absent (first zero-Digital day); pad heavily corrected, TOH box struck"),
    ("2026-08-28", None, None, None, None, None, "sheet never posted"),
    ("2026-08-30", 347, 375, 0, 40, 762, "all sections exact; Rakesh zero"),
    ("2026-08-31", 204, 571, 480, 0, 1255, "all sections exact; Digital 'Nill' written on pad"),
    ("2026-09-01", 874, 785, 406, 286, 2351,
     "J/S exact; Digital back from Nill; R rows sum 408 (+2), D rows sum 275 (-11) — minor read ambiguities"),
]

# Order sheet 3644 - colorway allocation (handwriting partly ambiguous)
# (colorway_file, marks, meters_interpreted, approved, confidence)
ORDER = [
    ("29793-ALL-AP-A (1).tif", "67 struck; 72; 49 below", "72", "rejected (X)", "low"),
    ("29793-ALL-AP-A (2).tif", "113 underlined; 13 below; 31+33", "113", "rejected (X)", "low"),
    ("29793-ALL-AP-A (7).tif", "41; 31; 90 underlined; 42+49; 50+10; -81 circled", "90", "rejected (X)", "low"),
    ("29793-ALL-AP-A (9).tif", "49; 59 mtr", "59", "rejected (X)", "low"),
    ("29793-ALL-AP-A (5?).tif", "84; 32 mtr; 25; 59", "32", "APPROVED (green check)", "med"),
]

ORDER_HEADER = {
    "order_no": 3644,
    "lot": 237,
    "party": "TAWAKKAL",
    "quality": "WEIGHTLESS-47",
    "dest": "IN[AM]",
    "order_date": "2026-08-12",
    "printed_note": "100 mtr per color",
    "hybrid": "struck through",
    "circled": ["244", "500 (1x5)", "2"],
    "right_column": [3218, 57, 71, 34, 34, 7, 50, 10, "sum 297"],
    "note": "35 grey chapai hai (orange, arrow to approved colorway)",
    "sign": "Humad Uttd (?)",
}


# Dispatch/packing sheets (Devanagari notebook, dispatch group 120363373350099610)
# (doc_date, page, section, item, qty, note, confidence)
DISPATCH = [
    ("2026-08-24", 34, "order_qty", "9159", 142, "", "med"),
    ("2026-08-24", 34, "order_qty", "4086", 625, "", "med"),
    ("2026-08-24", 34, "order_qty", "673", 495, "", "med"),
    ("2026-08-24", 34, "order_qty", "1132", 300, "", "med"),
    ("2026-08-24", 34, "order_qty", "426", 510, "", "med"),
    ("2026-08-24", 34, "order_qty", "GT-SCW-9743", 250, "", "med"),
    ("2026-08-24", 34, "order_qty", "5370", 320, "", "med"),
    ("2026-08-24", 34, "delivery_rate", "Dignity (डिग्निटी)", 29, "pallets, no outsourcing", "low"),
    ("2026-08-24", 34, "packed", "डिग्निटी (Dignity)", 200, "", "med"),
    ("2026-08-24", 34, "packed", "बेला (Bela)", 155, "", "med"),
    ("2026-08-24", 34, "packed", "भादरवती (Bhadravati)", "800 TP", "", "med"),
    ("2026-08-24", 34, "packed", "सीता (Sita)", 1000, "", "med"),
    ("2026-08-24", 34, "packed", "त्रिवेणी (Triveni)", 1200, "", "med"),
    ("2026-08-25", 37, "order_qty", "426-I", "800TP+207", "", "med"),
    ("2026-08-25", 37, "order_qty", "426-II", 93, "435 struck", "low"),
    ("2026-08-25", 37, "order_qty", "673", "45+10", "5 struck", "low"),
    ("2026-08-25", 37, "order_qty", "4086", "383+33RF+77", "packing note", "med"),
    ("2026-08-25", 37, "order_qty", "5370", "278+35", "", "med"),
    ("2026-08-25", 37, "order_qty", "9159", 118, "", "med"),
    ("2026-08-25", 37, "order_qty", "5370", 167, "second entry", "med"),
    ("2026-08-25", 37, "subtotal", "day", "2031 + 800TP / 107 -> 2138", "", "med"),
    ("2026-08-25", 37, "delivery_rate", "कफेमारिना (Kaferina?)", 9, "pallets -> transport", "low"),
    ("2026-08-25", 37, "packed", "राधेश (Radhesh)", 48, "", "low"),
    ("2026-08-25", 37, "packed", "मोतीबेगी (Motibegi?)", 1200, "", "low"),
    ("2026-08-25", 37, "packed", "सीता (Sita)", 1200, "", "med"),
    ("2026-08-25", 37, "packed", "श्रीजीग (Shreejeeg?)", 100, "", "low"),
    ("2026-08-25", 37, "packed", "डिग्निटी (Dignity)", 250, "", "med"),
    ("2026-08-25", 37, "packed", "बेला (Bela)", 155, "", "med"),
    ("2026-08-25", 37, "packed", "तहरती (Taharti?)", 100, "", "low"),
    ("2026-08-25", 37, "packed", "श्री बराफिर (Shree Barafir?)", 250, "", "low"),
    ("2026-08-25", 37, "packed", "प्रिमियम (Premium)", 250, "", "med"),
    ("2026-08-25", 37, "packed", "बलदेव दुइय (Baldev Duiya?)", 40, "", "low"),
    ("2026-08-25", 37, "packed", "त्रिवेणी (Triveni)", "800 TP", "", "med"),
    ("2026-08-25", 37, "packed_total", "day", "1193 + 3200 TP", "", "med"),
    ("2026-08-26", 39, "order_qty", "5370", 100, "", "med"),
    ("2026-08-26", 39, "order_qty", "1132", "596 RF", "", "med"),
    ("2026-08-26", 39, "order_qty", "9159", 178, "", "med"),
    ("2026-08-26", 39, "order_qty", "426", 360, "", "med"),
    ("2026-08-26", 39, "order_qty", "4086", 857, "struck", "low"),
    ("2026-08-26", 39, "order_qty", "1132", 185, "", "low"),
    ("2026-08-26", 39, "subtotal", "day", "1443 + 233RF = 1676", "", "med"),
    ("2026-08-26", 39, "delivery_rate", "रिंगु (Ringu)", 3, "pallets", "low"),
    ("2026-08-26", 39, "delivery_rate", "वगली (Vagali?)", 16, "70", "low"),
    ("2026-08-26", 39, "delivery_rate", "गाईड्स (Guides?)", 17, "77", "low"),
    ("2026-08-26", 39, "delivery_rate", "RD", 6, "77", "low"),
    ("2026-08-26", 39, "packed", "डिग्निटी इस्माइल (Dignity Ismail)", 100, "", "low"),
    ("2026-08-26", 39, "packed", "राधिरानी (Radhirani)", 200, "", "low"),
    ("2026-08-26", 39, "packed", "सनीप्रजा (Sunipraja?)", 100, "", "low"),
    ("2026-08-26", 39, "packed", "सातिमा (Satima?)", 144, "", "low"),
    ("2026-08-26", 39, "packed", "सीता (Sita)", 1200, "", "med"),
    ("2026-08-26", 39, "packed", "माधवपरी (Madhavpari?)", 1200, "", "low"),
    ("2026-08-26", 39, "packed", "त्रिवेणी (Triveni)", 1000, "", "med"),
    ("2026-08-26", 39, "packed", "राधेश (Radhesh)", 100, "", "low"),
    ("2026-08-26", 39, "packed", "उन्नतीलाल (Unnatilal)", 60, "", "low"),
    ("2026-08-26", 39, "packed", "बुलबुलीशिय (Bulbulishiya?)", 40, "", "low"),
    ("2026-08-26", 39, "packed", "बेला (Bela)", 155, "", "med"),
    ("2026-08-26", 99, "second_delivery", "Silver Exports", "73 Taka", "", "high"),
    ("2026-08-26", 99, "second_delivery", "Mateshwari Fashion", "14 Taka", "", "high"),
    ("2026-08-27", 41, "order_qty", "9159", 125, "", "med"),
    ("2026-08-27", 41, "order_qty", "5370", 155, "", "med"),
    ("2026-08-27", 41, "order_qty", "5370", 174, "second entry", "med"),
    ("2026-08-27", 41, "order_qty", "4086", "517+50", "", "med"),
    ("2026-08-27", 41, "order_qty", "673", 534, "", "med"),
    ("2026-08-27", 41, "order_qty", "1132", 448, "", "med"),
    ("2026-08-27", 41, "subtotal", "order 2003", 2003, "", "med"),
    ("2026-08-27", 41, "packed", "वगलमरुवा (Vagalmaruva?)", 90, "", "low"),
    ("2026-08-27", 41, "packed", "कुन्तीडियास (Kuntidias?)", 140, "", "low"),
    ("2026-08-27", 41, "packed", "कुन्तीलाल (Kuntilal)", 60, "", "low"),
    ("2026-08-27", 41, "packed", "सनैखुशी (Sunakhushi?)", 115, "", "low"),
    ("2026-08-27", 41, "packed", "गलहोग (Galahog?)", 75, "", "low"),
    ("2026-08-27", 41, "packed", "मिली (Mili)", 48, "", "low"),
    ("2026-08-27", 41, "packed", "हीरेलोग (Heerelog)", 100, "", "low"),
    ("2026-08-27", 41, "packed", "कमलोव (Kamalov)", 288, "", "low"),
    ("2026-08-27", 41, "packed", "राधारानी (Radharani)", 300, "", "low"),
    ("2026-08-27", 41, "packed", "विरामभाई (Virambhai)", 100, "", "low"),
    ("2026-08-27", 41, "packed", "VN", 150, "", "low"),
    ("2026-08-27", 41, "packed", "डिग्निटिखुशी (Dignity Khushi)", 80, "", "low"),
    ("2026-08-27", 41, "packed", "सीता (Sita)", 1200, "", "med"),
    ("2026-08-27", 41, "packed", "माधवपरी (Madhavpari)", 1200, "", "med"),
    ("2026-08-27", 41, "packed", "त्रिवेणी (Triveni)", 1000, "", "med"),
    ("2026-08-27", 41, "packed_total", "day", "1486 + 3400 TP", "", "med"),
    ("2026-08-28", 0, "second_delivery", "F Rangola (F रंगोला)", 115, "", "med"),
    ("2026-08-28", 0, "second_delivery", "Radharani (राधारानी)", 384, "", "med"),
    ("2026-08-28", 0, "subtotal", "day", 499, "", "med"),
    ("2026-08-29", 43, "order_qty", "673", 490, "", "med"),
    ("2026-08-29", 43, "order_qty", "5370", 275, "", "med"),
    ("2026-08-29", 43, "order_qty", "1132", "1212 TP", "", "med"),
    ("2026-08-29", 43, "order_qty", "1132", 47, "", "med"),
    ("2026-08-29", 43, "delivery_report", "करनी कृपा (Karni Kripa)", "31 pallets", "", "low"),
    ("2026-08-29", 43, "delivery_report", "RD", "14 pallets", "", "low"),
    ("2026-08-29", 43, "delivery_report", "हीरेलोग (Heerelog)", "36 bags", "", "low"),
    ("2026-08-29", 43, "delivery_report", "सीता (Sita)", "35 bags", "", "low"),
    ("2026-08-29", 43, "delivery_report", "रघुवीर (Raghuvir)", "9 T pallets", "", "low"),
    ("2026-08-29", 43, "delivery_report", "वागनेश्वरी (Vagheshwari)", "18", "", "low"),
    ("2026-08-29", 43, "delivery_report", "KV", "16", "", "low"),
    ("2026-08-29", 43, "delivery_report", "D.C", "6", "", "low"),
    ("2026-08-29", 43, "delivery_report", "डिगाम्बर (Digambar)", "9", "", "low"),
    ("2026-08-29", 43, "packed", "उगालगुप्ता (Ugal Gupta?)", 80, "", "low"),
    ("2026-08-29", 43, "packed", "वगतीवला (Vagivala?)", 300, "", "low"),
    ("2026-08-29", 43, "packed", "डिग्निटिखुशी (Dignity Khushi)", 80, "", "low"),
    ("2026-08-29", 43, "packed", "कुन्तीडिया (Kuntidia)", 140, "", "low"),
    ("2026-08-29", 43, "packed", "हीरेलोग (Heerelog)", 100, "", "low"),
    ("2026-08-29", 43, "packed", "कुन्तीलाल (Kuntilal)", 60, "", "low"),
    ("2026-08-29", 43, "packed", "गलहोग (Galahog?)", 25, "", "low"),
    ("2026-08-29", 43, "packed", "कमलोव (Kamalov)", 288, "", "low"),
    ("2026-08-29", 43, "packed", "मिली (Mili)", 48, "", "low"),
    ("2026-08-29", 43, "packed", "वगतोताकना (Vagototakna?)", 20, "", "low"),
    ("2026-08-29", 43, "packed", "VV", 150, "", "low"),
    ("2026-08-29", 43, "packed", "माधवपरी (Madhavpari)", 1200, "", "med"),
    ("2026-08-29", 43, "packed", "त्रिवेणी (Triveni)", 1000, "", "med"),
    ("2026-08-29", 43, "packed", "डिगाम्बर (Digambar)", 100, "", "low"),
    ("2026-08-29", 43, "packed", "त्रिवेणीप्रिंट (Triveni Print)", 80, "", "low"),
    ("2026-08-29", 43, "packed", "बाडपट (Badapt?)", 32, "", "low"),
    ("2026-08-29", 43, "packed_total", "day", "1543 + 2200 TP", "", "med"),
    ("2026-08-30", 44, "packed", "मगनलाल (Maganlal)", 20, "", "low"),
    ("2026-08-30", 44, "packed", "गगडोला (Gagdola)", 104, "", "low"),
    ("2026-08-30", 44, "packed", "कपयुमारील (Kapyumaril?)", 72, "", "low"),
    ("2026-08-30", 44, "packed", "डिगाम्बर (Digambar)", 100, "", "low"),
    ("2026-08-30", 44, "packed", "हीरेलोग (Heerelog)", 115, "", "low"),
    ("2026-08-30", 44, "packed_total", "day", 411, "rows sum exactly", "med"),
    ("2026-08-30", 0, "godown_photo", "inventory state", None,
     "packed thana bags + printed fabric piles on floor (visual evidence, not a sheet)", "info"),
    ("2026-08-31", 0, "jobwork_challan", "Mukesh Texfab", "282.3 m",
     "batch VL103?, 3 pieces, quality Bosboss/MS? — grey sent to outside process house", "low"),
    ("2026-08-31", 0, "jobwork_challan", "Mukesh Texfab", "1081.7 m",
     "batch VL201 NAT?, 10 pieces (110.3/81/101.3/114.35/121.5/120.5/98/125.5/103/106)", "med"),
    ("2026-08-31", 0, "godown_photo", "inventory state", None,
     "packed grey thana stacks", "info"),
    ("2026-09-01", 0, "chat_screenshot", "forwarded godown photo + complaint thread", None,
     "'Camical vala abhi tk uthaya nahi he' — chemical-lease pickup pending", "med"),
    ("2026-09-01", 47, "order_qty", "4086", 617, "digit struck", "low"),
    ("2026-09-01", 47, "order_qty", "9159", 110, "", "med"),
    ("2026-09-01", 47, "order_qty", "9159", 60, "", "med"),
    ("2026-09-01", 47, "order_qty", "1132", "317+150", "34 pallets", "med"),
    ("2026-09-01", 47, "order_qty", "673", 315, "", "med"),
    ("2026-09-01", 47, "order_qty", "9159", 94, "", "med"),
    ("2026-09-01", 47, "order_qty", "4824", None, "no qty written", "low"),
    ("2026-09-01", 47, "order_qty", "GJ21", 323, "", "low"),
    ("2026-09-01", 47, "order_qty", "5370", 264, "", "med"),
    ("2026-09-01", 47, "packed", "कुलशीशिया (Kulshishia?)", 650, "", "low"),
    ("2026-09-01", 47, "packed", "डिग्निटीखुशी (Dignity Khushi)", 30, "", "low"),
    ("2026-09-01", 47, "packed", "तहरती (Taharti?)", 50, "", "low"),
    ("2026-09-01", 47, "packed", "कनकदीप्ति (Kanakdipti?)", 350, "", "low"),
    ("2026-09-01", 47, "packed", "हीरेलोग RF (Heerelog RF)", 40, "", "low"),
    ("2026-09-01", 47, "packed", "BS RF", 50, "", "low"),
    ("2026-09-01", 47, "packed", "बलदेवसतापिता (Baldev Satapita?)", 48, "", "low"),
    ("2026-09-01", 47, "packed", "SK", 72, "", "low"),
    ("2026-09-01", 47, "packed", "वगपग (Vagpag?)", 48, "", "low"),
    ("2026-09-01", 47, "packed", "कमलोव (Kamalov)", 288, "", "low"),
    ("2026-09-01", 47, "packed", "माधवपरी (Madhavpari)", "1200 TP", "", "med"),
    ("2026-09-01", 47, "packed", "त्रिवेणी (Triveni)", "1000 TP", "", "med"),
    ("2026-09-01", 47, "packed", "सीता (Sita)", "400 TP", "", "med"),
    ("2026-09-01", 47, "packed_total", "day", "1536 + 90RF + 4600 TP", "", "med"),
    ("2026-09-02", 0, "notice", "FOSTTA circular", None,
     "All Surat cloth markets CLOSED 04/09/2026 (Krishna Janmashtami) — plant holiday; "
     "grey sheet/production reports expected absent; missing-doc detectors must skip this date", "high"),
]


def write_dispatch(out_dir: Path = OUT) -> None:
    with (out_dir / "dispatch_packing.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["doc_date", "page", "section", "item", "qty", "note", "ocr_confidence"])
        w.writerows(DISPATCH)


# White & finish route (group 120363409903031213 'Swastik digital white & finish.')
# Daily lot-level finishing sheets: <lot>-<taka> | quality | mill/step | process | width"
# (sheet_date, lot_no, quality, mill_step, process, width_in, taka, note, confidence)
WHITE_FINISH = [
    ("2026-08-28", "2037-12", "Wetless 7800", "MF", "F", 45, 12, "", "med"),
    ("2026-08-28", "2038-12", "Wetless 7800", "MF", "F", 45, 12, "", "med"),
    ("2026-08-28", "2039-12", "Wetless 7800", "MF", "F", 45, 12, "", "med"),
    ("2026-08-28", "2040-12", "Wetless 7800", "MF", "F", 45, 12, "", "med"),
    ("2026-08-28", "2041-12", "Wetless 7800", "MF", "F", 45, 12, "", "med"),
    ("2026-08-28", "2042-12", "Wetless 7800", "MF", "F", 45, 12, "", "med"),
    ("2026-08-28", "1856-25", "Wetless 7800", "MF", "F", 45, 25, "", "med"),
    ("2026-08-28", "1895-25", "Wetless 8kg", "DB", "S", 45, 25, "", "med"),
    ("2026-08-28", "1896-25", "Wetless 8kg", "DB", "S", 45, 25, "", "med"),
    ("2026-08-28", "TOTAL", "", "", "", None, 117, "rows sum 147 — total reads 117/147, ambiguous", "low"),
    ("2026-08-28", "NOTE", "", "", "", None, None, "28/08 'This Date I am on the leave' (DHAVVAL) — sheet sent 29th morning", "high"),
    ("2026-08-29", "2053-12", "Wetless 7800", "MF", "F", 45, 12, "", "med"),
    ("2026-08-29", "2054-12", "Wetless 7800", "MF", "F", 45, 12, "", "med"),
    ("2026-08-29", "2055-12", "Wetless 7800", "MF", "F", 45, 12, "", "med"),
    ("2026-08-29", "2056-12", "Wetless 7800", "MF", "F", 45, 12, "", "med"),
    ("2026-08-29", "2057-25", "20x20 Bright", "Shanti", "S", 59, 25, "party=Shanti visible on this row", "med"),
    ("2026-08-29", "2058-12", "Wetless 7800", "MF", "F", 45, 12, "", "med"),
    ("2026-08-29", "TOTAL", "", "", "", None, 97, "rows sum exactly", "high"),
    ("2026-08-30", "1358-72", "Wetless 58in", "RSE", "F", 59, 72, "", "med"),
    ("2026-08-30", "1357-48", "Wetless 58in", "RSE", "F", 59, 48, "written 118, red-corrected 48", "med"),
    ("2026-08-30", "TOTAL", "", "", "", None, 120, "rows sum exactly", "high"),
    ("2026-08-31", "1867-25", "Wetless 8kg", "DB", "S", 45, 25, "", "med"),
    ("2026-08-31", "1868-25", "Wetless 8kg", "DB", "S", 45, 25, "", "med"),
    ("2026-08-31", "1872-25", "Wetless 8kg", "DB", "S", 45, 25, "", "med"),
    ("2026-08-31", "TOTAL", "", "", "", None, 75, "rows sum exactly", "high"),
    ("2026-09-01", "1961-10", "Wetless 58in", "SLS", "F", 59, 10, "", "med"),
    ("2026-09-01", "1962-10", "Wetless 58in", "SLS", "F", 59, 10, "", "med"),
    ("2026-09-01", "1963-10", "Wetless 58in", "SLS", "F", 59, 10, "", "med"),
    ("2026-09-01", "1964-10", "Wetless 58in", "SLS", "F", 59, 10, "", "med"),
    ("2026-09-01", "1965-10", "Wetless 58in", "SLS", "F", 59, 10, "", "med"),
    ("2026-09-01", "1966-10", "Wetless 58in", "SLS", "F", 59, 10, "", "med"),
    ("2026-09-01", "1967-10", "Wetless 58in", "SLS", "F", 59, 10, "", "med"),
    ("2026-09-01", "1968-10", "Wetless 58in", "SLS", "F", 59, 10, "", "med"),
    ("2026-09-01", "1969-10", "Wetless 58in", "SLS", "F", 59, 10, "", "med"),
    ("2026-09-01", "1970-10", "Wetless 58in", "SLS", "F", 59, 10, "", "med"),
    ("2026-09-01", "2074-17", "Wetless 58in", "RSE", "F", 59, 17, "", "med"),
    ("2026-09-01", "TOTAL", "", "", "", None, 117, "rows sum exactly", "high"),
    ("2026-09-02", "2102-22", "20x20 Bright", "ASE", "S", 59, 22, "", "med"),
    ("2026-09-02", "2058-50", "20x20 nature", "Agile", "S", 45, 50, "", "med"),
    ("2026-09-02", "1862-10", "Wetless 7800", "SLS", "F", 45, 10, "", "med"),
    ("2026-09-02", "1863-20", "Wetless 7800", "SLS", "F", 45, 20, "", "med"),
    ("2026-09-02", "1864-20", "Wetless 7800", "SLS", "F", 45, 20, "", "med"),
    ("2026-09-02", "1865-20", "Wetless 7800", "SLS", "F", 45, 20, "", "med"),
    ("2026-09-02", "1866-20", "Wetless 7800", "SLS", "F", 45, 20, "", "med"),
    ("2026-09-02", "1868-25", "Wetless 8kg", "DB", "S", 45, 25, "", "med"),
    ("2026-09-02", "1870-25", "Wetless 8kg", "DB", "S", 45, 25, "", "med"),
    ("2026-09-02", "1871-25", "Wetless 8kg", "DB", "S", 45, 25, "", "med"),
    ("2026-09-02", "TOTAL", "", "", "", None, 237, "rows sum exactly", "high"),
]


def write_white_finish(out_dir: Path = OUT) -> None:
    with (out_dir / "white_finish.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["sheet_date", "lot_no", "quality", "mill_step", "process",
                    "width_in", "taka", "note", "ocr_confidence"])
        w.writerows(WHITE_FINISH)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "grey_inward_lines.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["sheet_date", "section", "party", "quality", "taka", "ocr_confidence"])
        w.writerows(LINES)
    with (OUT / "grey_inward_sheets.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["sheet_date", "jafar", "sunil", "rakesh", "digital", "toh", "note"])
        w.writerows(SHEETS)
    with (OUT / "order_3644_colorways.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["colorway_file", "handwritten_marks", "meters", "status", "ocr_confidence"])
        w.writerows(ORDER)
    import json
    (OUT / "order_3644_header.json").write_text(
        json.dumps(ORDER_HEADER, indent=2, ensure_ascii=False), encoding="utf-8")
    write_dispatch()
    write_white_finish()
    print(f"wrote 6 files to {OUT}")
    print(f"grey_inward_lines: {len(LINES)} rows, "
          f"taka total {sum(r[4] for r in LINES if isinstance(r[4], int))} "
          f"(sheets TOH sum {sum(s[5] for s in SHEETS if isinstance(s[5], int))})")


if __name__ == "__main__":
    main()







