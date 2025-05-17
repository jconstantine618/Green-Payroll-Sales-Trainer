# ──────────────────────────────────────────────────────────────────────────────
#  Green Payroll – Sales-Trainer Chatbot  (Streamlit + OpenAI + ElevenLabs TTS)
#  Full standalone script                                                      
# ──────────────────────────────────────────────────────────────────────────────
import os, json, time, base64, pathlib, sqlite3, datetime
import streamlit as st
import openai

# Optional: fall-back TTS
from gtts import gTTS

# ──────────────────────────────────────────────────────────────────────────────
#  ElevenLabs setup (audio in memory → Streamlit)
# ──────────────────────────────────────────────────────────────────────────────
try:
    from elevenlabs import generate as el_generate
    ELEVEN_KEY = st.secrets.get("ELEVEN_API_KEY") or os.getenv("ELEVEN_API_KEY")
except ModuleNotFoundError:
    ELEVEN_KEY = None

def tts_bytes(text: str, voice: str = "Rachel"):
    """
    Return speech as raw MP3 bytes.
    Falls back to gTTS if ElevenLabs key/module unavailable.
    """
    if ELEVEN_KEY:
        return el_generate(
            text=text,
            voice=voice,
            model="eleven_multilingual_v2",
            api_key=ELEVEN_KEY,
        )
    # Fallback
    g = gTTS(text)
    from io import BytesIO
    buf = BytesIO()
    g.write_to_fp(buf)
    return buf.getvalue()

# ──────────────────────────────────────────────────────────────────────────────
#  Lite SQLite leaderboard
# ──────────────────────────────────────────────────────────────────────────────
DB = pathlib.Path(__file__).parent / "leaderboard.db"
conn = sqlite3.connect(DB, check_same_thread=False)
cur  = conn.cursor()
cur.execute(
    "CREATE TABLE IF NOT EXISTS leaderboard "
    "(id INTEGER PRIMARY KEY, name TEXT, score INT, timestamp TEXT)"
)
conn.commit()

# ──────────────────────────────────────────────────────────────────────────────
#  Sales-skills heuristics
# ──────────────────────────────────────────────────────────────────────────────
PILLARS = {
    "rapport": ["i understand", "great question", "thank you for sharing"],
    "pain":    ["challenge", "issue", "pain point", "concern"],
    "needs":   ["what system", "how much time", "are you confident", "success look"],
    "teach":   ["did you know", "we've seen", "benchmark", "tailor"],
    "close":   ["demo", "free trial", "does this sound", "next step", "move forward"],
}
FEEDBACK_HINTS = {
    "rapport": "Work on building rapport by showing empathy, thanking them for insights, or using mirroring language.",
    "pain":    "Ask more about challenges or frustrations in their current system to uncover pain points.",
    "needs":   "You missed some great discovery opportunities. Ask what success looks like or how much time they spend.",
    "teach":   "Try educating them with a quick insight or customer story that reframes their thinking.",
    "close":   "You're missing a closing action—suggest a next step like a demo or free trial.",
}
COMPLIMENTS = {
    "rapport": "Nice rapport building—your tone is friendly and shows good emotional intelligence.",
    "pain":    "You did a great job uncovering the root challenges that matter.",
    "needs":   "Your discovery questions were spot-on.",
    "teach":   "Well done reframing their thinking with relevant examples.",
    "close":   "Excellent closing! You moved the conversation forward with confidence.",
}

DEAL_OBJECTIONS = [
    "budget", "timing", "vendor switching", "implementation",
    "support", "internal approval"
]

def calc_score(msgs):
    counts = {p: 0 for p in PILLARS}
    for m in msgs:
        if m["role"] != "user":
            continue
        txt = m["content"].lower()
        for p, kws in PILLARS.items():
            if any(k in txt for k in kws):
                counts[p] += 1

    subs   = {p: min(v, 3) * (20/3) for p, v in counts.items()}
    total  = int(sum(subs.values()))
    fb     = [f"{'✅' if pts >= 10 else '⚠️'} {p.title()} {int(pts)}/20"
              for p, pts in subs.items()]

    insights = [COMPLIMENTS[p] if pts >= 15 else FEEDBACK_HINTS[p]
                for p, pts in subs.items()]
    details  = "\n\n".join(f"**{p.title()}**: {insights[i]}"
                           for i, p in enumerate(PILLARS))

    convo      = " ".join(m["content"].lower()
                          for m in msgs if m["role"] == "user")
    uncovered  = [o for o in DEAL_OBJECTIONS if o in convo]
    missed     = [o for o in DEAL_OBJECTIONS if o not in uncovered]
    objections = (
        f"**Objections you uncovered:** {', '.join(uncovered) or 'None'}"
        f"\n**Objections you missed:** {', '.join(missed) or 'None'}"
    )
    return total, "\n".join(fb), subs, details + "\n\n" + objections

# ──────────────────────────────────────────────────────────────────────────────
#  Generate post-call narrative
# ──────────────────────────────────────────────────────────────────────────────
def generate_follow_up_narrative(sub_scores, scenario, persona):
    name, company = persona["persona_name"], scenario["prospect"]
    score         = int(sum(sub_scores.values()))
    close         = sub_scores.get("close", 0)
    rapport       = sub_scores.get("rapport", 0)
    pain          = sub_scores.get("pain", 0)

    if score >= 75 and close >= 10:
        return (f"You and {name} agreed it made sense to review your proposal "
                f"together. You presented a solution and it was accepted. "
                f"{company} will soon become a strong long-term client.")
    if score >= 50 and close >= 5:
        return (f"You left a solid impression. {name} asked for a deeper pricing "
                f"breakdown before presenting internally. A second call is "
                f"scheduled next week.")
    if score >= 35 and rapport >= 10 and pain >= 5:
        return (f"You got a short reply: {name} said they’re reviewing internally "
                f"and may reach out later this month. Persistence required.")
    return (f"You followed up, but after two weeks of silence it appears "
            f"{name} has moved on with another provider. Opportunity lost.")

# ──────────────────────────────────────────────────────────────────────────────
#  Timer helpers
# ──────────────────────────────────────────────────────────────────────────────
def init_timer():
    if "start" not in st.session_state:
        st.session_state.start = time.time()
        st.session_state.cut   = False
    elapsed   = (time.time() - st.session_state.start) / 60
    remaining = st.session_state.time_cap - elapsed
    st.sidebar.markdown("### ⏱️ Time Remaining")
    if remaining <= 1 and not st.session_state.cut:
        st.sidebar.warning("⚠️ Less than 1 minute!")
    elif remaining <= 3:
        st.sidebar.info(f"⏳ {int(remaining)} min left")
    else:
        st.sidebar.write(f"{int(remaining)} minutes remaining")

def is_time_up():
    return (time.time() - st.session_state.start) / 60 >= st.session_state.time_cap

# ──────────────────────────────────────────────────────────────────────────────
#  OpenAI client
# ──────────────────────────────────────────────────────────────────────────────
OPENAI_KEY = st.secrets.get("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
if not OPENAI_KEY:
    st.error("OPENAI_API_KEY missing")
    st.stop()
client = openai.OpenAI(api_key=OPENAI_KEY)

# ──────────────────────────────────────────────────────────────────────────────
#  Data load (scenarios)
# ──────────────────────────────────────────────────────────────────────────────
DATA      = pathlib.Path(__file__).parent / "data" / "greenpayroll_scenarios.json"
SCENARIOS = json.loads(DATA.read_text())

# ──────────────────────────────────────────────────────────────────────────────
#  Streamlit Page
# ──────────────────────────────────────────────────────────────────────────────
st.set_page_config("Green Payroll Sales Trainer", "💬")
st.title("💬 Green Payroll – Sales-Training Chatbot")

# Playbook download (optional)
pdf = pathlib.Path(__file__).parent / "GreenPayroll Sales Playbook.pdf"
if pdf.exists():
    b64  = base64.b64encode(pdf.read_bytes()).decode()
    href = f"data:application/pdf;base64,{b64}"
    st.sidebar.markdown(
        f'<a href="{href}" download="GreenPayroll_Playbook.pdf"'
        f' style="text-decoration:none">'
        f'<div style="background:#28a745;padding:8px;border-radius:4px;'
        f'text-align:center;color:white">'
        f'Download Sales Playbook</div></a>', unsafe_allow_html=True)

# Scenario selector
labels = [f"{s['id']}. {s['prospect']} ({s['category']})" for s in SCENARIOS]
choice = st.sidebar.selectbox("Choose a scenario", labels)
voice  = st.sidebar.checkbox("🎙️ Read assistant replies aloud")

scenario = SCENARIOS[labels.index(choice)]
persona  = scenario["decision_makers"][0]

# quick difficulty heuristics
hard_kw   = ["multi-state", "compliance", "remote", "credential",
             "stipend", "garnishment"]
medium_kw = ["tip", "brewery", "multiple locations", "over 50", "union"]

def diff(s):
    desc = s.get("prospect_description", "").lower()
    if any(w in desc for w in hard_kw):   return ("Hard", 20)
    if any(w in desc for w in medium_kw): return ("Medium", 15)
    return ("Easy", 10)

level, minutes = diff(scenario)
st.session_state.time_cap = minutes

st.markdown(f"""
**Persona:** {persona['persona_name']} ({persona['persona_role']})  
**Background:** {persona['persona_background']}  
**Company:** {scenario['prospect']}  
**Difficulty:** {level}  
**Time Available:** {minutes} min
""")

# ──────────────────────────────────────────────────────────────────────────────
#  System prompt
# ──────────────────────────────────────────────────────────────────────────────
system_prompt = f"""
You are **{persona['persona_name']}**, **{persona['persona_role']}** at **{scenario['prospect']}**.
Stay strictly in character, realistic objections & tone.

Green Payroll talking points:
- All-in-One Workforce Platform (payroll, benefits, time, onboarding)
- Dedicated Service Team (named account manager)
- Compliance Peace-of-Mind (proactive alerts)
- Seamless Integrations (QuickBooks, ERP, ATS)
- Typical client gains: save 4-6 h/wk, fewer errors, scale without extra HR

Expect discovery Q’s like:
- "What system are you using now?"
- "What challenges do you face?"
- "How much time is payroll taking?"
- "Are you confident in compliance?"
- "What does success look like?"

Preferred closing moves:
- Offer demo
- Offer free trial
- "Does this sound like a fit?"
- Schedule next step

End the call once {minutes} min pass or if rep wastes time.
"""

# ──────────────────────────────────────────────────────────────────────────────
#  Session-state init
# ──────────────────────────────────────────────────────────────────────────────
if "scenario" not in st.session_state or st.session_state.scenario != choice:
    st.session_state.scenario = choice
    st.session_state.msgs = [{"role": "system", "content": system_prompt}]
    st.session_state.closed = False
    st.session_state.score  = ""

init_timer()

# ──────────────────────────────────────────────────────────────────────────────
#  Chat input handling
# ──────────────────────────────────────────────────────────────────────────────
user_txt = st.chat_input("Your message to the prospect")
if user_txt and not st.session_state.closed:
    st.session_state.msgs.append({"role": "user", "content": user_txt})

    if is_time_up():
        st.session_state.msgs.append({
            "role": "assistant",
            "content": f"**{persona['persona_name']}**: Sorry, I need to hop to another meeting."
        })
        st.session_state.closed = True
    else:
        rsp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=st.session_state.msgs
        )
        reply = rsp.choices[0].message.content.strip()
        st.session_state.msgs.append({"role": "assistant", "content": reply})

# ──────────────────────────────────────────────────────────────────────────────
#  Render conversation + optional TTS
# ──────────────────────────────────────────────────────────────────────────────
for m in st.session_state.msgs[1:]:
    st.chat_message("user" if m["role"] == "user" else "assistant").write(m["content"])
    if voice and m["role"] == "assistant":
        st.audio(tts_bytes(m["content"]), format="audio/mp3")

# ──────────────────────────────────────────────────────────────────────────────
#  Sidebar controls
# ──────────────────────────────────────────────────────────────────────────────
if st.sidebar.button("🔄 Reset Chat"):
    st.session_state.clear()
    st.rerun()

if st.sidebar.button("🔚 End & Score"):
    if not st.session_state.closed:
        total, fb, subs, detail = calc_score(st.session_state.msgs)
        st.session_state.closed          = True
        st.session_state.score_value     = total
        st.session_state.sub_scores      = subs
        st.session_state.feedback_detail = detail
        st.session_state.score           = f"🏆 **Score {total}/100**\n\n{fb}"
        st.sidebar.success("Scored!")

# ──────────────────────────────────────────────────────────────────────────────
#  Show results (if any) & leaderboard
# ──────────────────────────────────────────────────────────────────────────────
if st.session_state.score:
    story = generate_follow_up_narrative(
        st.session_state.sub_scores, scenario, persona
    )
    st.sidebar.markdown("### 📘 What Happened Next")
    st.sidebar.markdown(story)
    st.sidebar.markdown(st.session_state.score)

    st.sidebar.markdown("### 🧩 Score Breakdown")
    for k, v in st.session_state.sub_scores.items():
        st.sidebar.write(f"{k.title()}: {int(v)}/20")

    st.sidebar.markdown("### 📣 Suggestions")
    st.sidebar.markdown(st.session_state.feedback_detail)

    name = st.sidebar.text_input("Name:", key="nm")
    if st.sidebar.button("🏅 Save to Leaderboard") and name:
        cur.execute(
            "INSERT INTO leaderboard(name,score,timestamp) VALUES(?,?,?)",
            (name, st.session_state.score_value, datetime.datetime.now())
        )
        conn.commit()

    st.sidebar.write("### Top 10")
    for i, (n, s) in enumerate(
        cur.execute(
            "SELECT name,score FROM leaderboard "
            "ORDER BY score DESC, timestamp ASC LIMIT 10"
        ), start=1
    ):
        st.sidebar.write(f"{i}. {n} — {s}")
