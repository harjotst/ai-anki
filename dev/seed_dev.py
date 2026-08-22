"""Seed the dev database with a believable study history.

Everything goes through the server's own code paths where they exist:
enrol() introduces cards, rebuild() replays the log through real FSRS.
Only the raw facts (accounts, decks, cards, review rows) are SQL, because
seeding IS inventing facts.
"""
import json, random, sys
from datetime import datetime, timedelta

sys.path.insert(0, ".")
from app import db, social, study

random.seed(41)
TZ = datetime.now().astimezone().tzinfo
DEV = "00000000-0000-0000-0000-0000000000aa"
MAYA = "00000000-0000-0000-0000-0000000000bb"
TODAY = datetime(2026, 8, 22, tzinfo=TZ)

def d(y, m, day, h=12):
    return datetime(y, m, day, h, tzinfo=TZ)

DECKS = [
    ("d-enzyme", "Enzyme Kinetics", d(2026, 7, 14)),
    ("d-cardiac", "Cardiac Physiology", d(2026, 7, 28)),
    ("d-renal", "Renal Physiology", d(2026, 8, 19)),
]

# (deck, topic, note_type, front, back)
CARDS = [
    ("d-enzyme", "michaelis-menten", "basic",
     "What does the Michaelis constant (Km) represent?",
     "The substrate concentration at which velocity is half of Vmax. A low Km means high apparent affinity of the enzyme for its substrate."),
    ("d-enzyme", "michaelis-menten", "cloze",
     "In Michaelis-Menten kinetics, Vmax is reached when the enzyme is {{c1::saturated with substrate}}.",
     "At saturation every active site is occupied, so adding substrate cannot speed the reaction further."),
    ("d-enzyme", "inhibition", "basic",
     "How does a competitive inhibitor change Km and Vmax?",
     "Km increases (apparent affinity falls); Vmax is unchanged — enough substrate can still outcompete the inhibitor."),
    ("d-enzyme", "inhibition", "basic",
     "How does a noncompetitive inhibitor change Km and Vmax?",
     "Vmax decreases; Km is unchanged. It binds away from the active site, so affinity is untouched but a fraction of enzyme is always disabled."),
    ("d-enzyme", "inhibition", "cloze",
     "On a Lineweaver-Burk plot, competitive inhibition moves the {{c1::x-intercept (−1/Km)}} while the y-intercept stays fixed.",
     "Vmax (y-intercept, 1/Vmax) is unchanged; apparent Km grows, pulling −1/Km toward zero."),
    ("d-enzyme", "michaelis-menten", "basic",
     "What is the turnover number (kcat)?",
     "Reactions catalyzed per enzyme molecule per second at saturation: kcat = Vmax / [E]total."),
    ("d-enzyme", "michaelis-menten", "basic",
     "What does the ratio kcat/Km measure?",
     "Catalytic efficiency at low substrate concentration. Its ceiling is the diffusion limit, about 10^8–10^9 M⁻¹s⁻¹."),
    ("d-enzyme", "allostery", "cloze",
     "Allosteric enzymes give a {{c1::sigmoidal}} velocity curve rather than a hyperbolic one.",
     "Cooperative binding: occupancy at one site raises affinity at the others."),
    ("d-enzyme", "inhibition", "basic",
     "Why does aspirin inhibit COX enzymes permanently?",
     "It acetylates a serine in the active site — covalent, irreversible inhibition. Activity returns only with synthesis of new enzyme."),
    ("d-enzyme", "inhibition", "basic",
     "How does an uncompetitive inhibitor change Km and Vmax?",
     "Both decrease, in parallel. It binds only the enzyme–substrate complex, locking substrate in."),
    ("d-enzyme", "allostery", "cloze",
     "Phosphofructokinase-1 is allosterically inhibited by {{c1::ATP and citrate}}.",
     "High-energy signals slow glycolysis; AMP and fructose-2,6-bisphosphate reverse the inhibition."),
    ("d-enzyme", "michaelis-menten", "basic",
     "Enzymes accelerate reactions by lowering what quantity?",
     "The activation energy (ΔG‡). Equilibrium is untouched — an enzyme changes how fast, never how far."),
    ("d-cardiac", "cardiac-cycle", "basic",
     "What events define isovolumetric contraction?",
     "Both valves closed: from mitral closure to aortic opening, the ventricle contracts and pressure rises at constant volume."),
    ("d-cardiac", "cardiac-cycle", "cloze",
     "The mitral valve closes when {{c1::ventricular pressure exceeds atrial pressure}} — the start of systole (S1).",
     "S1 is the sound of the AV valves closing as ventricular pressure overtakes atrial pressure."),
    ("d-cardiac", "cardiac-cycle", "basic",
     "What produces the S2 heart sound?",
     "Closure of the aortic and pulmonic valves at the start of diastole."),
    ("d-cardiac", "pressure-volume", "basic",
     "Define ejection fraction and give its normal range.",
     "EF = stroke volume / end-diastolic volume; normally 55–70%."),
    ("d-cardiac", "pressure-volume", "cloze",
     "Stroke volume = {{c1::end-diastolic volume − end-systolic volume}}.",
     "Typically about 120 mL − 50 mL = 70 mL at rest."),
    ("d-cardiac", "pressure-volume", "basic",
     "State the Frank-Starling law.",
     "Greater venous return stretches the ventricle; the increased preload strengthens contraction, so stroke volume rises with end-diastolic volume — no nerves required."),
    ("d-cardiac", "ecg", "basic",
     "What does the PR interval represent, and what is its normal length?",
     "Atrial depolarization plus AV-node delay; 120–200 ms."),
    ("d-cardiac", "ecg", "cloze",
     "The plateau (phase 2) of the ventricular action potential is carried by {{c1::inward Ca²⁺ current balanced against outward K⁺}}.",
     "The calcium entering during the plateau is what triggers calcium-induced calcium release."),
    ("d-cardiac", "ecg", "basic",
     "Why does the AV node delay conduction?",
     "Its slow calcium-dependent upstroke lets atrial contraction finish filling the ventricles before they contract."),
    ("d-cardiac", "ecg", "basic",
     "How does sympathetic stimulation raise heart rate?",
     "Noradrenaline on β1 receptors steepens phase-4 depolarization in SA-node cells by raising funny current (If) and Ca²⁺ conductance."),
    ("d-cardiac", "pressure-volume", "cloze",
     "Pulse pressure = {{c1::systolic minus diastolic pressure}}.",
     "It widens when stroke volume rises or arterial compliance falls, as in aging."),
    ("d-cardiac", "pressure-volume", "basic",
     "What is afterload, and what most directly increases it?",
     "The pressure the ventricle must overcome to eject — approximated by systemic arterial pressure. Hypertension and aortic stenosis raise it."),
    ("d-renal", "filtration", "basic",
     "What three layers form the glomerular filtration barrier?",
     "Fenestrated capillary endothelium, the basement membrane, and podocyte foot processes with slit diaphragms."),
    ("d-renal", "clearance", "cloze",
     "GFR is estimated clinically with {{c1::creatinine clearance}}, which slightly overestimates true GFR.",
     "Creatinine is also secreted by the proximal tubule, so its clearance runs a little above filtration."),
    ("d-renal", "clearance", "basic",
     "Write the clearance formula.",
     "C = (U × V̇) / P — urine concentration times urine flow rate, divided by plasma concentration."),
    ("d-renal", "filtration", "basic",
     "Why does efferent arteriole constriction raise filtration fraction?",
     "It raises glomerular capillary pressure (GFR up) while lowering renal plasma flow — so FF = GFR/RPF rises on both counts."),
    ("d-renal", "filtration", "basic",
     "Where is most filtered sodium reabsorbed?",
     "The proximal tubule — roughly 65–70%, isosmotically with water."),
    ("d-renal", "filtration", "cloze",
     "The thick ascending limb is impermeable to {{c1::water}}, making it the diluting segment.",
     "Salt leaves without water, so tubular fluid becomes hypotonic while the interstitium concentrates."),
    ("d-renal", "clearance", "basic",
     "What does ADH do at the collecting duct?",
     "Inserts aquaporin-2 channels into the apical membrane → water reabsorption → concentrated urine."),
    ("d-renal", "clearance", "basic",
     "How does aldosterone change potassium handling?",
     "Principal cells reabsorb Na⁺ and secrete K⁺ — aldosterone excess therefore causes hypokalemia."),
    ("d-renal", "filtration", "basic",
     "What is a normal GFR?",
     "About 125 mL/min — roughly 180 L filtered per day."),
    ("d-renal", "clearance", "cloze",
     "Inulin is the gold-standard GFR marker because it is {{c1::freely filtered, neither reabsorbed nor secreted}}.",
     "Everything filtered appears in urine, so its clearance equals GFR exactly."),
]

LESSON_MM = {
    "in_one_line": "Michaelis-Menten kinetics describes how reaction speed saturates as substrate rises, summarized by just two numbers: Km and Vmax.",
    "why_it_matters": "Half of pharmacology is a fight over an active site. Reading Km and Vmax off a curve tells you what a drug, a mutation, or a poison is doing to an enzyme.",
    "sections": [
        {"heading": "The curve itself", "body": "Velocity rises almost linearly at low substrate, then bends and flattens toward Vmax as active sites fill. The concentration at half of Vmax is Km — the whole model in one landmark.", "builds_on": None},
        {"heading": "What Km is really telling you", "body": "Km is an inverse affinity gauge: a low Km enzyme grabs scarce substrate well. Hexokinase (low Km) works everywhere; glucokinase (high Km) only responds when glucose floods in after a meal — same reaction, different job, told apart by Km alone.", "builds_on": "The curve itself"},
        {"heading": "kcat and efficiency", "body": "Vmax depends on how much enzyme you loaded, so it is not a property of the enzyme itself. Divide it by enzyme concentration and you get kcat, the turnover number; kcat/Km is the efficiency at physiologic (low) substrate and tops out at the diffusion limit.", "builds_on": "What Km is really telling you"},
    ],
    "worked_example": {
        "problem": "An enzyme has Vmax 100 µmol/min and Km 2 mM. What is the velocity at 2 mM substrate, and at very high substrate with a competitive inhibitor present?",
        "walkthrough": "At [S] = Km, velocity is by definition half of Vmax: 50 µmol/min. With a competitive inhibitor, apparent Km rises but Vmax stays 100 — at very high substrate the inhibitor is outcompeted and velocity still approaches 100 µmol/min.",
    },
    "misconceptions": [
        {"belief": "A low Km means a slow enzyme.", "why_it_is_wrong": "Km says nothing about speed — it locates the curve on the concentration axis. Speed at saturation is kcat's job; an enzyme can have a tiny Km and a lazy kcat, or the reverse."},
        {"belief": "Enzymes shift the equilibrium toward product.", "why_it_is_wrong": "They lower activation energy and reach equilibrium faster. The final ratio of product to substrate is set by ΔG and is identical with or without the enzyme."},
    ],
    "check_yourself": [
        "Your patient overdosed on methanol; ethanol is given as therapy. Which inhibition pattern is this, and what happens to the apparent Km of alcohol dehydrogenase for methanol?",
        "Why does measuring Vmax alone tell you nothing about an enzyme's efficiency in vivo?",
    ],
}

LESSON_CC = {
    "in_one_line": "The cardiac cycle is two valves per side opening and closing in strict order, and every sound, waveform and murmur maps onto one of those events.",
    "why_it_matters": "Auscultation, ECG timing, and every pressure tracing on a monitor are the cardiac cycle read in different alphabets. Learn the sequence once and all three become the same story.",
    "sections": [
        {"heading": "Systole in two acts", "body": "Act one: the mitral valve closes (S1) and the ventricle squeezes a fixed volume — isovolumetric contraction. Act two: pressure beats the aorta, the aortic valve opens, blood leaves. Ejection ends as pressure falls and the aortic valve slams shut (S2).", "builds_on": None},
        {"heading": "Diastole is not passive rest", "body": "After isovolumetric relaxation the mitral valve opens and the ventricle fills — mostly early and passively, topped off by atrial kick. Lose that kick to atrial fibrillation and a stiff ventricle loses real output.", "builds_on": "Systole in two acts"},
        {"heading": "Reading it as pressure", "body": "The whole cycle is one loop on a pressure–volume plot: width is stroke volume, and the area inside is stroke work. Preload moves the right edge, afterload the top, contractility the tilt of the end-systolic corner.", "builds_on": "Diastole is not passive rest"},
    ],
    "worked_example": {
        "problem": "EDV is 130 mL and ESV is 60 mL. Give the stroke volume and ejection fraction, and say whether the EF is normal.",
        "walkthrough": "SV = 130 − 60 = 70 mL. EF = 70/130 ≈ 54%, a whisker below the usual 55–70% band — borderline, worth an echo rather than a diagnosis.",
    },
    "misconceptions": [
        {"belief": "S1 and S2 are the sounds of blood hitting the ventricle walls.", "why_it_is_wrong": "They are valve-closure sounds: AV valves for S1, semilunar valves for S2. Flow itself is silent unless it turns turbulent — which is what a murmur is."},
    ],
    "check_yourself": [
        "During which phase are all four valves closed, and how many times does that happen per beat?",
        "Why does inspiration split S2?",
    ],
}

conn = db.connect(db.dsn())
now = db.now() if hasattr(db, "now") else datetime.now(TZ)

conn.execute(
    "INSERT INTO account (id, email, display_name, is_admin, created_at) VALUES (%s,%s,%s,%s,%s)"
    " ON CONFLICT (id) DO NOTHING",
    (DEV, "dev@local.test", "Harjot", True, d(2026, 7, 14)))
conn.execute(
    "INSERT INTO account (id, email, display_name, is_admin, created_at) VALUES (%s,%s,%s,%s,%s)"
    " ON CONFLICT (id) DO NOTHING",
    (MAYA, "maya@local.test", "Maya Chen", False, d(2026, 7, 20)))
social.friend_code(conn, DEV)
social.friend_code(conn, MAYA)

for deck_id, name, created in DECKS:
    conn.execute("INSERT INTO deck (id, account_id, name, created_at) VALUES (%s,%s,%s,%s)"
                 " ON CONFLICT (id) DO NOTHING", (deck_id, DEV, name, created))
    job_id = deck_id.replace("d-", "j-")
    conn.execute("INSERT INTO job (deck_id, id, account_id, state, created_at) VALUES (%s,%s,%s,'complete',%s)"
                 " ON CONFLICT (id) DO NOTHING", (deck_id, job_id, DEV, created))

topics_seen = set()
for position, (deck_id, topic, note_type, front, back) in enumerate(CARDS):
    job_id = deck_id.replace("d-", "j-")
    deck_name = dict((d_, n) for d_, n, _ in DECKS)[deck_id]
    path = f"{deck_name}::{topic.replace('-', ' ').title()}"
    if (job_id, topic) not in topics_seen:
        topics_seen.add((job_id, topic))
        conn.execute(
            "INSERT INTO topic (job_id, topic_id, position, status, topic_json) VALUES (%s,%s,%s,'complete',%s)"
            " ON CONFLICT DO NOTHING",
            (job_id, topic, len(topics_seen), json.dumps({"topic_id": topic, "path": path, "difficulty": "medium"})))
    conn.execute(
        "INSERT INTO card (job_id, card_uuid, topic_id, deck_path, note_type, front, back,"
        "                  difficulty, deck_id, question_fingerprint, position)"
        " VALUES (%s,%s,%s,%s,%s,%s,%s,'medium',%s,%s,%s) ON CONFLICT DO NOTHING",
        (job_id, f"c-{deck_id[2:]}-{position:02d}", topic, path, note_type, front, back,
         deck_id, front.lower()[:80], position))

conn.execute("INSERT INTO lesson (job_id, topic_id, deck_path, lesson_json, created_at) VALUES"
             " ('j-enzyme','michaelis-menten','Enzyme Kinetics::Michaelis Menten',%s,%s)"
             " ON CONFLICT DO NOTHING", (json.dumps(LESSON_MM), d(2026, 7, 14, 13)))
conn.execute("INSERT INTO lesson (job_id, topic_id, deck_path, lesson_json, created_at) VALUES"
             " ('j-cardiac','cardiac-cycle','Cardiac Physiology::Cardiac Cycle',%s,%s)"
             " ON CONFLICT DO NOTHING", (json.dumps(LESSON_CC), d(2026, 7, 28, 13)))

# Friendship: accepted, requested by Maya.
low, high = sorted([DEV, MAYA])
conn.execute("INSERT INTO friendship (account_low, account_high, state, requested_by, created_at)"
             " VALUES (%s,%s,'accepted',%s,%s) ON CONFLICT DO NOTHING",
             (low, high, MAYA, d(2026, 8, 10)))
# Maya studies the enzyme deck too.
conn.execute("INSERT INTO deck_member (deck_id, account_id, shared_by, created_at)"
             " VALUES ('d-enzyme',%s,%s,%s) ON CONFLICT DO NOTHING", (MAYA, DEV, d(2026, 8, 12)))

for account, deck_id in [(DEV, "d-enzyme"), (DEV, "d-cardiac"), (DEV, "d-renal"), (MAYA, "d-enzyme")]:
    study.enrol(conn, account, deck_id)

# --- history ---------------------------------------------------------------
# Dev: Aug 5..21 inclusive, every day. Cards are introduced over the first
# days of their deck's life and re-reviewed on rough SRS offsets.
uuids = {}
for position, (deck_id, *_rest) in enumerate(CARDS):
    uuids.setdefault(deck_id, []).append(f"c-{deck_id[2:]}-{position:02d}")

def insert_review(account, card, when, rating, tag):
    conn.execute(
        "INSERT INTO review (account_id, client_uuid, card_uuid, rating, reviewed_at, duration_ms, received_at)"
        " VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (account_id, client_uuid) DO NOTHING",
        (account, f"seed-{tag}", card, rating, when, random.randint(2500, 14000),
         when + timedelta(seconds=3)))

touched = set()
serial = 0
def study_day(account, card, day, hour_base=19):
    global serial
    serial += 1
    when = day.replace(hour=hour_base) + timedelta(minutes=random.randint(0, 110), seconds=serial % 60)
    rating = random.choices([1, 2, 3, 4], weights=[10, 12, 62, 16])[0]
    insert_review(account, card, when, rating, f"{account[-2:]}-{serial}")
    touched.add((account, card))
    return rating

first_dev_day = d(2026, 8, 5)
for i, card in enumerate(uuids["d-enzyme"]):
    intro = first_dev_day + timedelta(days=i % 4)          # Aug 5-8
    offsets = [0, 1, 3, 7, 13]
    for off in offsets:
        day = intro + timedelta(days=off)
        if day <= d(2026, 8, 21):
            study_day(DEV, card, day)
for i, card in enumerate(uuids["d-cardiac"]):
    intro = d(2026, 8, 9) + timedelta(days=i % 5)          # Aug 9-13
    for off in [0, 1, 3, 7]:
        day = intro + timedelta(days=off)
        if day <= d(2026, 8, 21):
            study_day(DEV, card, day)
for card in uuids["d-renal"][:4]:                          # yesterday, once
    study_day(DEV, card, d(2026, 8, 21))
# Fill any thin days so the streak is airtight Aug 5-21.
for day_off in range(17):
    day = first_dev_day + timedelta(days=day_off)
    study_day(DEV, random.choice(uuids["d-enzyme"]), day, hour_base=8)

for i, card in enumerate(uuids["d-enzyme"][:8]):           # Maya: lighter
    intro = d(2026, 8, 15) + timedelta(days=i % 3)
    for off in [0, 2, 5]:
        day = intro + timedelta(days=off)
        if day <= d(2026, 8, 21):
            study_day(MAYA, card, day)

for account, card in sorted(touched):
    study.rebuild(conn, account, card)

conn.commit()

# --- report ----------------------------------------------------------------
due = conn.execute("SELECT count(*) AS n FROM study_card WHERE account_id=%s AND due <= now()", (DEV,)).fetchone()
total = conn.execute("SELECT count(*) AS n FROM review WHERE account_id=%s", (DEV,)).fetchone()
days = conn.execute("SELECT count(DISTINCT date(reviewed_at)) AS n FROM review WHERE account_id=%s", (DEV,)).fetchone()
print(f"dev: {total['n']} reviews over {days['n']} days, {due['n']} cards due now")
maya = conn.execute("SELECT count(*) AS n FROM review WHERE account_id=%s", (MAYA,)).fetchone()
print(f"maya: {maya['n']} reviews")
