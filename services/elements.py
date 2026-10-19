"""the periodic table for andromeda's element and periodic-table answers.

standard atomic weights (IUPAC, abridged); a value in brackets is the mass number of the
longest-lived isotope. group 0 marks the lanthanide and actinide rows.
"""

# number symbol name mass group period category
_TABLE = """
1 H Hydrogen 1.008 1 1 nonmetal
2 He Helium 4.0026 18 1 noble-gas
3 Li Lithium 6.94 1 2 alkali-metal
4 Be Beryllium 9.0122 2 2 alkaline-earth
5 B Boron 10.81 13 2 metalloid
6 C Carbon 12.011 14 2 nonmetal
7 N Nitrogen 14.007 15 2 nonmetal
8 O Oxygen 15.999 16 2 nonmetal
9 F Fluorine 18.998 17 2 halogen
10 Ne Neon 20.180 18 2 noble-gas
11 Na Sodium 22.990 1 3 alkali-metal
12 Mg Magnesium 24.305 2 3 alkaline-earth
13 Al Aluminium 26.982 13 3 post-transition
14 Si Silicon 28.085 14 3 metalloid
15 P Phosphorus 30.974 15 3 nonmetal
16 S Sulfur 32.06 16 3 nonmetal
17 Cl Chlorine 35.45 17 3 halogen
18 Ar Argon 39.95 18 3 noble-gas
19 K Potassium 39.098 1 4 alkali-metal
20 Ca Calcium 40.078 2 4 alkaline-earth
21 Sc Scandium 44.956 3 4 transition
22 Ti Titanium 47.867 4 4 transition
23 V Vanadium 50.942 5 4 transition
24 Cr Chromium 51.996 6 4 transition
25 Mn Manganese 54.938 7 4 transition
26 Fe Iron 55.845 8 4 transition
27 Co Cobalt 58.933 9 4 transition
28 Ni Nickel 58.693 10 4 transition
29 Cu Copper 63.546 11 4 transition
30 Zn Zinc 65.38 12 4 transition
31 Ga Gallium 69.723 13 4 post-transition
32 Ge Germanium 72.630 14 4 metalloid
33 As Arsenic 74.922 15 4 metalloid
34 Se Selenium 78.971 16 4 nonmetal
35 Br Bromine 79.904 17 4 halogen
36 Kr Krypton 83.798 18 4 noble-gas
37 Rb Rubidium 85.468 1 5 alkali-metal
38 Sr Strontium 87.62 2 5 alkaline-earth
39 Y Yttrium 88.906 3 5 transition
40 Zr Zirconium 91.224 4 5 transition
41 Nb Niobium 92.906 5 5 transition
42 Mo Molybdenum 95.95 6 5 transition
43 Tc Technetium [98] 7 5 transition
44 Ru Ruthenium 101.07 8 5 transition
45 Rh Rhodium 102.91 9 5 transition
46 Pd Palladium 106.42 10 5 transition
47 Ag Silver 107.87 11 5 transition
48 Cd Cadmium 112.41 12 5 transition
49 In Indium 114.82 13 5 post-transition
50 Sn Tin 118.71 14 5 post-transition
51 Sb Antimony 121.76 15 5 metalloid
52 Te Tellurium 127.60 16 5 metalloid
53 I Iodine 126.90 17 5 halogen
54 Xe Xenon 131.29 18 5 noble-gas
55 Cs Caesium 132.91 1 6 alkali-metal
56 Ba Barium 137.33 2 6 alkaline-earth
57 La Lanthanum 138.91 0 6 lanthanide
58 Ce Cerium 140.12 0 6 lanthanide
59 Pr Praseodymium 140.91 0 6 lanthanide
60 Nd Neodymium 144.24 0 6 lanthanide
61 Pm Promethium [145] 0 6 lanthanide
62 Sm Samarium 150.36 0 6 lanthanide
63 Eu Europium 151.96 0 6 lanthanide
64 Gd Gadolinium 157.25 0 6 lanthanide
65 Tb Terbium 158.93 0 6 lanthanide
66 Dy Dysprosium 162.50 0 6 lanthanide
67 Ho Holmium 164.93 0 6 lanthanide
68 Er Erbium 167.26 0 6 lanthanide
69 Tm Thulium 168.93 0 6 lanthanide
70 Yb Ytterbium 173.05 0 6 lanthanide
71 Lu Lutetium 174.97 0 6 lanthanide
72 Hf Hafnium 178.49 4 6 transition
73 Ta Tantalum 180.95 5 6 transition
74 W Tungsten 183.84 6 6 transition
75 Re Rhenium 186.21 7 6 transition
76 Os Osmium 190.23 8 6 transition
77 Ir Iridium 192.22 9 6 transition
78 Pt Platinum 195.08 10 6 transition
79 Au Gold 196.97 11 6 transition
80 Hg Mercury 200.59 12 6 transition
81 Tl Thallium 204.38 13 6 post-transition
82 Pb Lead 207.2 14 6 post-transition
83 Bi Bismuth 208.98 15 6 post-transition
84 Po Polonium [209] 16 6 post-transition
85 At Astatine [210] 17 6 halogen
86 Rn Radon [222] 18 6 noble-gas
87 Fr Francium [223] 1 7 alkali-metal
88 Ra Radium [226] 2 7 alkaline-earth
89 Ac Actinium [227] 0 7 actinide
90 Th Thorium 232.04 0 7 actinide
91 Pa Protactinium 231.04 0 7 actinide
92 U Uranium 238.03 0 7 actinide
93 Np Neptunium [237] 0 7 actinide
94 Pu Plutonium [244] 0 7 actinide
95 Am Americium [243] 0 7 actinide
96 Cm Curium [247] 0 7 actinide
97 Bk Berkelium [247] 0 7 actinide
98 Cf Californium [251] 0 7 actinide
99 Es Einsteinium [252] 0 7 actinide
100 Fm Fermium [257] 0 7 actinide
101 Md Mendelevium [258] 0 7 actinide
102 No Nobelium [259] 0 7 actinide
103 Lr Lawrencium [266] 0 7 actinide
104 Rf Rutherfordium [267] 4 7 transition
105 Db Dubnium [268] 5 7 transition
106 Sg Seaborgium [269] 6 7 transition
107 Bh Bohrium [270] 7 7 transition
108 Hs Hassium [269] 8 7 transition
109 Mt Meitnerium [278] 9 7 transition
110 Ds Darmstadtium [281] 10 7 transition
111 Rg Roentgenium [282] 11 7 transition
112 Cn Copernicium [285] 12 7 transition
113 Nh Nihonium [286] 13 7 post-transition
114 Fl Flerovium [289] 14 7 post-transition
115 Mc Moscovium [290] 15 7 post-transition
116 Lv Livermorium [293] 16 7 post-transition
117 Ts Tennessine [294] 17 7 halogen
118 Og Oganesson [294] 18 7 noble-gas
"""

CATEGORY_LABELS = {
    "nonmetal": "nonmetal",
    "noble-gas": "noble gas",
    "alkali-metal": "alkali metal",
    "alkaline-earth": "alkaline earth metal",
    "metalloid": "metalloid",
    "halogen": "halogen",
    "post-transition": "post-transition metal",
    "transition": "transition metal",
    "lanthanide": "lanthanide",
    "actinide": "actinide",
}


def _parse() -> list[dict]:
    rows = []
    for line in _TABLE.strip().splitlines():
        number, symbol, name, mass, group, period, category = line.split()
        rows.append(
            {
                "number": int(number),
                "symbol": symbol,
                "name": name,
                "mass": mass,
                "group": int(group),
                "period": int(period),
                "category": category,
            }
        )
    return rows


ELEMENTS = _parse()
BY_NAME = {row["name"].lower(): row for row in ELEMENTS}
BY_NAME.update({"aluminum": BY_NAME["aluminium"], "cesium": BY_NAME["caesium"]})
BY_SYMBOL = {row["symbol"].lower(): row for row in ELEMENTS}
