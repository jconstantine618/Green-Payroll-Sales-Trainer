"""
Green Payroll – Sales‑Training Chatbot  •  v1
------------------------------------------------
Key additions pulled from the official B2B Sales Playbook:
 • Persona prompt now embeds Green Payroll’s value props, benefits,
   common discovery questions, and preferred closing moves.
 • Updated colour theme + playbook‑driven wording throughout.
"""

import streamlit as st, openai, os, json, pathlib, time, sqlite3, datetime, base64
from gtts import gTTS

# ── DATABASE ────────────────────────────────────────────────────────────────────
DB = pathlib.Path(__file__).parent / "leaderboard.db"
conn = sqlite3.connect(DB, check_same_thread=False)
cur = conn.cursor()
cur.execute("""CREATE TABLE IF NOT EXISTS leaderboard
               (id INTEGER PRIMARY KEY, name TEXT, score INT, timestamp TEXT)""")
conn.commit()

# ── SALES PILLARS & SCORING ─────────────────────────────────────────────────────
PILLARS = {
    "rapport":  ["i understand", "great question", "thank you for sharing"],
    "pain":     ["challenge", "issue", "pain point", "concern"],
    "needs":    ["what system", "how much time", "are you confident", "success look"],
    "teach":    ["did you know", "we've seen", "benchmark", "tailor"],
    "close":    ["demo", "free trial", "does this sound", "next step", "move forward"]
}

def calc_score(msgs):
    counts = {p: 0 for p in PILLARS}
    for m in msgs:
        if m["role"] != "user": continue
        txt = m["content"].lower()
        for p, kws in PILLARS.items():
            if any(k in txt for k in kws):
                counts[p] += 1
    subs = {p: min(v, 3) * (20/3) for p, v in counts.items()}
    total = int(sum(subs.values()))
    fb = [f"{'✅' if pts>=10 else '⚠️'} {p.title()} {int(pts)}/20"
          for p, pts in subs.items()]
    return total, "\n".join(fb)

# ── TIMER HELPERS ───────────────────────────────────────────────────────────────
def init_timer():
    if "start" not in st.session_state:
        st.session_state.start = time.time()
        st.session_state.cut = False
def time_cap(window):
    limit = {"<5":5,"5-10":10,"10-15":15}.get(window,10)
    return (time.time()-st.session_state.start)/60 >= limit

# ── OPENAI CLIENT ───────────────────────────────────────────────────────────────
api = st.secrets.get("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
if not api: st.error("OPENAI_API_KEY missing"); st.stop()
client = openai.OpenAI(api_key=api)

# ── LOAD SCENARIOS ──────────────────────────────────────────────────────────────
DATA = pathlib.Path(__file__).parent / "data" / "greenpayroll_scenarios.json"
SCENARIOS = json.loads(DATA.read_text())

# ── PAGE SET‑UP ─────────────────────────────────────────────────────────────────
st.set_page_config(page_title="Green Payroll Sales Trainer", page_icon="💬")
st.title("💬 Green Payroll — Sales‑Training Chatbot")

# Playbook download (optional)
pdf = pathlib.Path(__file__).parent / "GreenPayroll Sales Playbook.pdf"
if pdf.exists():
    st.sidebar.markdown(
        f'<a href="data:application/pdf;base64,{base64.b64encode(pdf.read_bytes()).decode()}" '
        f'download="GreenPayroll_Playbook.pdf" style="text-decoration:none">'
        f'<div style="background:#28a745;padding:8px;border-radius:4px;text-align:center;color:white">'
        f'Download Sales Playbook</div></a>', unsafe_allow_html=True)

# Scenario selector
names = [f"{s['id']}. {s['prospect']} ({s['category']})" for s in SCENARIOS]
pick  = st.sidebar.selectbox("Choose a scenario", names)
voice = st.sidebar.checkbox("🎙️ Voice Playback")

S = SCENARIOS[names.index(pick)]
P = S["decision_makers"][0]

st.markdown(f"""
**Persona:** {P['persona_name']} ({P['persona_role']})  
**Background:** {P['persona_background']}  
**Company:** {S['prospect']}  
**Difficulty:** {S['difficulty']['level']}  
**Time Available:** {P['time_availability']['window']} min
""")

# ── SYSTEM PROMPT (playbook‑driven) ─────────────────────────────────────────────
sys = f"""
You are **{P['persona_name']}**, **{P['persona_role']}** at **{S['prospect']}**.

Stay strictly in character using realistic objections & tone.

▼ Green Payroll facts you know (share only when relevant):
• All‑in‑One Workforce Platform (payroll, benefits, time, onboarding)  
• Dedicated Service Team (named account mgr)  
• Compliance Peace‑of‑Mind (proactive alerts)  
• Seamless Integrations (QuickBooks, etc.)  
• Typical client gains: save 4‑6 h/wk, lower errors, scale without extra HR staff :contentReference[oaicite:2]{index=2}:contentReference[oaicite:3]{index=3}

▼ Common discovery questions you expect to hear:
  “What system are you using now?” • “What challenges do you face?” •
  “How much time is payroll taking?” • “Are you confident in compliance?” •
  “What does success look like?”

▼ Preferred closing approaches:
  • Offer demo  • Offer free trial  • “Does this sound like a fit?”  • Next‑step scheduling.

You have {P['time_availability']['window']} min for this call. End it if the rep wastes time.
"""

# ── SESSION STATE ───────────────────────────────────────────────────────────────
if "scenario" not in st.session_state or st.session_state.scenario != pick:
    st.session_state.scenario = pick
    st.session_state.msgs = [{"role":"system","content":sys}]
    st.session_state.closed = False
    st.session_state.score = ""

init_timer()

# Chat input
text = st.chat_input("Your message to the prospect")
if text and not st.session_state.closed:
    st.session_state.msgs.append({"role":"user","content":text})
    if time_cap(P["time_availability"]["window"]):
        st.session_state.msgs.append({"role":"assistant",
            "content":f"**{P['persona_name']}**: Sorry, I need to hop to another meeting."})
        st.session_state.closed = True
    else:
        rsp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=st.session_state.msgs
        )
        ans = rsp.choices[0].message.content.strip()
        st.session_state.msgs.append({"role":"assistant","content":ans})

# Render chat
for m in st.session_state.msgs[1:]:
    st.chat_message("user" if m["role"]=="user" else "assistant").write(m["content"])
    if voice and m["role"]=="assistant":
        gTTS(m["content"]).save("tmp.mp3")
        st.audio(open("tmp.mp3","rb").read(), format="audio/mp3")

# Sidebar controls
if st.sidebar.button("🔄 Reset Chat"):
    st.session_state.clear(); st.rerun()

if st.sidebar.button("🔚 End & Score"):
    if not st.session_state.closed:
        total, fb = calc_score(st.session_state.msgs)
        st.session_state.closed = True
        st.session_state.score = f"🏆 **Score {total}/100**\n\n{fb}"
        st.sidebar.success("Scored!")

if st.session_state.score:
    st.sidebar.markdown(st.session_state.score)
    if st.sidebar.button("🏅 Save to Leaderboard"):
        name = st.sidebar.text_input("Name:", key="nm")
        if name:
            cur.execute("INSERT INTO leaderboard(name,score,timestamp) VALUES(?,?,?)",
                        (name,int(st.session_state.score.split()[1].split('/')[0]),
                         datetime.datetime.now()))
            conn.commit()
    st.sidebar.write("### Top 10")
    for i,(n,s) in enumerate(cur.execute(
        "SELECT name,score FROM leaderboard ORDER BY score DESC,timestamp ASC LIMIT 10"),1):
        st.sidebar.write(f"{i}. {n} — {s}")
