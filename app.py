import streamlit as st
import openai
import os
import json
import pathlib
import time
import sqlite3
import datetime
import base64
from gtts import gTTS

# -- DATABASE -------------------------------------------------------------
DB = pathlib.Path(__file__).parent / "leaderboard.db"
conn = sqlite3.connect(DB, check_same_thread=False)
cur = conn.cursor()
cur.execute(
    """
    CREATE TABLE IF NOT EXISTS leaderboard
    (id INTEGER PRIMARY KEY, name TEXT, score INT, timestamp TEXT)
    """
)
conn.commit()

# -- SALES PILLARS & SCORING ---------------------------------------------
PILLARS = {
    "rapport": ["i understand", "great question", "thank you for sharing"],
    "pain": ["challenge", "issue", "pain point", "concern"],
    "needs": ["what system", "how much time", "are you confident", "success look"],
    "teach": ["did you know", "we've seen", "benchmark", "tailor"],
    "close": ["demo", "free trial", "does this sound", "next step", "move forward"]
}

FEEDBACK_HINTS = {
    "rapport": "Work on building rapport by showing empathy, thanking them for insights, or using mirroring language.",
    "pain": "Ask more about challenges or frustrations in their current system to uncover pain points.",
    "needs": "You missed some great discovery opportunities. Ask what success looks like or how much time they spend.",
    "teach": "Try educating them with a quick insight or customer story that reframes their thinking.",
    "close": "You're missing a closing action—suggest a next step like a demo or free trial."
}

COMPLIMENTS = {
    "rapport": "Nice rapport building—your tone is friendly and shows good emotional intelligence.",
    "pain": "You did a great job uncovering the root challenges that matter.",
    "needs": "Your discovery questions were spot-on.",
    "teach": "Well done reframing their thinking with relevant examples.",
    "close": "Excellent closing! You moved the conversation forward with confidence."
}

DEAL_OBJECTIONS = [
    "budget", "timing", "vendor switching", "implementation", "support", "internal approval"
]

# -- SCORING FUNCTION -----------------------------------------------------
def calc_score(msgs):
    counts = {p: 0 for p in PILLARS}
    for m in msgs:
        if m["role"] != "user":
            continue
        txt = m["content"].lower()
        for p, kws in PILLARS.items():
            if any(k in txt for k in kws):
                counts[p] += 1

    subs = {p: min(v, 3) * (20 / 3) for p, v in counts.items()}
    total = int(sum(subs.values()))
    fb = [f"{'✅' if pts >= 10 else '⚠️'} {p.title()} {int(pts)}/20" for p, pts in subs.items()]

    insights = [COMPLIMENTS[p] if pts >= 15 else FEEDBACK_HINTS[p] for p, pts in subs.items()]
    feedback_detail = "\n\n".join(
        [f"**{p.title()}**: {insights[i]}" for i, p in enumerate(PILLARS)]
    )

    # Check for objection coverage
    conversation = " ".join(
        [m["content"].lower() for m in msgs if m["role"] == "user"]
    )
    uncovered = [o for o in DEAL_OBJECTIONS if o in conversation]
    missed = [o for o in DEAL_OBJECTIONS if o not in uncovered]
    objection_summary = f"""
**Objections you uncovered:** {', '.join(uncovered) if uncovered else 'None'}"""
    objection_summary += f"""
**Objections you missed:** {', '.join(missed) if missed else 'None'}"""

    feedback_detail += objection_summary
    return total, "\n".join(fb), subs, feedback_detail

# -- TIMER HELPERS --------------------------------------------------------
def init_timer():
    if "start" not in st.session_state:
        st.session_state.start = time.time()
        st.session_state.cut = False
    st.sidebar.markdown("### ⏱️ Time Remaining")
    elapsed = (time.time() - st.session_state.start) / 60
    max_time = P["time_availability"]["window"]
    remaining = max_time - elapsed
    if remaining <= 1 and not st.session_state.cut:
        st.sidebar.warning("⚠️ Less than 1 minute remaining!")
    elif remaining <= 3:
        st.sidebar.info(f"⏳ {int(remaining)} minutes left")
    else:
        st.sidebar.write(f"{int(remaining)} minutes remaining")

def time_cap(window):
    return (time.time() - st.session_state.start) / 60 >= window

# -- OPENAI CLIENT --------------------------------------------------------
api = st.secrets.get("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
if not api:
    st.error("OPENAI_API_KEY missing")
    st.stop()
client = openai.OpenAI(api_key=api)

# -- LOAD SCENARIOS -------------------------------------------------------
DATA = pathlib.Path(__file__).parent / "data" / "greenpayroll_scenarios.json"
SCENARIOS = json.loads(DATA.read_text())

# -- PAGE SETUP -----------------------------------------------------------
st.set_page_config(page_title="Green Payroll Sales Trainer", page_icon="💬")
st.title("💬 Green Payroll - Sales Training Chatbot")

# Optional: Sales Playbook Download
pdf = pathlib.Path(__file__).parent / "GreenPayroll Sales Playbook.pdf"
if pdf.exists():
    b64 = base64.b64encode(pdf.read_bytes()).decode()
    st.sidebar.markdown(
        f'<a href="data:application/pdf;base64,{b64}" download="GreenPayroll_Playbook.pdf" '
        f'style="text-decoration:none"><div '
        f'style="background:#28a745;padding:8px;border-radius:4px;text-align:center;color:white">'
        f'Download Sales Playbook</div></a>',
        unsafe_allow_html=True
    )

# Scenario selector
names = [f"{s['id']}. {s['prospect']} ({s['category']})" for s in SCENARIOS]
pick = st.sidebar.selectbox("Choose a scenario", names)
voice = st.sidebar.checkbox("🎙️ Voice Playback")

S = SCENARIOS[names.index(pick)]

# -- Assess Difficulty Dynamically ----------------------------------------
def assess_difficulty(scenario):
    desc = scenario.get("prospect_description", "").lower()
    if any(word in desc for word in ["multi-state", "compliance", "remote", "credential", "stipend", "garnishment"]):
        return "Hard", 20
    elif any(word in desc for word in ["tip", "brewery", "multiple locations", "over 50", "union"]):
        return "Medium", 15
    else:
        return "Easy", 10

S["difficulty"] = {"level": assess_difficulty(S)[0]}
P = S["decision_makers"][0]
P["time_availability"]["window"] = assess_difficulty(S)[1]

st.markdown(f"""
**Persona:** {P['persona_name']} ({P['persona_role']})  
**Background:** {P['persona_background']}  
**Company:** {S['prospect']}  
**Difficulty:** {S['difficulty']['level']}  
**Time Available:** {P['time_availability']['window']} min
""")

# -- SYSTEM PROMPT --------------------------------------------------------
sys = f"""
You are **{P['persona_name']}**, **{P['persona_role']}** at **{S['prospect']}**.

Stay strictly in character using realistic objections & tone.

- Green Payroll facts you may reference:
- All-in-One Workforce Platform (payroll, benefits, time, onboarding)
- Dedicated Service Team (named account manager)
- Compliance Peace-of-Mind (proactive alerts)
- Seamless Integrations (QuickBooks, ERP, ATS)
- Typical client gains: save 4-6 h/wk, lower errors, scale without extra HR staff

- Common discovery questions you expect:
  "What system are you using now?" - "What challenges do you face?" -
  "How much time is payroll taking?" - "Are you confident in compliance?" -
  "What does success look like?"

- Preferred closing approaches:
  - Offer demo
  - Offer free trial
  - "Does this sound like a fit?"
  - Next-step scheduling.

You have {P['time_availability']['window']} min for this call. 
