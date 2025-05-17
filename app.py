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

# ── DATABASE ───────────────────────────────────────
DB = pathlib.Path(__file__).parent / "leaderboard.db"
conn = sqlite3.connect(DB, check_same_thread=False)
cur = conn.cursor()
cur.execute("""CREATE TABLE IF NOT EXISTS leaderboard
               (id INTEGER PRIMARY KEY, name TEXT, score INT, timestamp TEXT)""")
conn.commit()

# ── SALES PILLARS & SCORING ────────────────────────
PILLARS = {
    "rapport":  ["i understand", "great question", "thank you for sharing"],
    "pain":     ["challenge", "issue", "pain point", "concern"],
    "needs":    ["what system", "how much time", "are you confident", "success look"],
    "teach":    ["did you know", "we've seen", "benchmark", "tailor"],
    "close":    ["demo", "free trial", "does this sound", "next step", "move forward"]
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

def generate_follow_up_narrative(sub_scores, scenario, persona):
    name = persona["persona_name"]
    company = scenario["prospect"]
    score = int(sum(sub_scores.values()))
    close_score = sub_scores.get("close", 0)
    rapport = sub_scores.get("rapport", 0)
    pain = sub_scores.get("pain", 0)

    if score >= 75 and close_score >= 10:
        return f"You and {name} agreed it made sense to review your proposal together. When you returned, they were warm, receptive, and clearly remembered your previous conversation. You presented a solution and it was accepted. {company} will soon become a strong long-term client."
    elif score >= 50 and close_score >= 5:
        return f"You left a solid impression. {name} asked for a deeper breakdown of pricing before presenting internally. A second call is scheduled next week to walk through next steps."
    elif score >= 35 and rapport >= 10 and pain >= 5:
        return f"You followed up via email and got a short reply. {name} said they’re reviewing internally and may reach out later this month. It’s still an open opportunity, but it will require persistence."
    else:
        return f"You left a voicemail and sent a follow-up email, but didn’t hear back. After two weeks of silence, it’s safe to assume {name} has moved on with another provider. This opportunity is marked as lost."


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
    fb = [f"{'✅' if pts>=10 else '⚠️'} {p.title()} {int(pts)}/20" for p, pts in subs.items()]

    insights = [COMPLIMENTS[p] if pts >= 15 else FEEDBACK_HINTS[p] for p, pts in subs.items()]
    feedback_detail = "\n\n".join([f"**{p.title()}**: {insights[i]}" for i, p in enumerate(PILLARS)])

    return total, "\n".join(fb), subs, feedback_detail

# ── TIMER HELPERS ──────────────────────────────────
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
    limit = window
    return (time.time()-st.session_state.start)/60 >= limit

# ── OPENAI CLIENT ──────────────────────────────────
api = st.secrets.get("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
if not api:
    st.error("OPENAI_API_KEY missing"); st.stop()
client = openai.OpenAI(api_key=api)

# ── LOAD SCENARIOS ─────────────────────────────────
DATA = pathlib.Path(__file__).parent / "data" / "greenpayroll_scenarios.json"
SCENARIOS = json.loads(DATA.read_text())

# ── PAGE SETUP ─────────────────────────────────────
st.set_page_config(page_title="Green Payroll Sales Trainer", page_icon="💬")
st.title("💬 Green Payroll – Sales Training Chatbot")

# Optional: Sales Playbook Download
pdf = pathlib.Path(__file__).parent / "GreenPayroll Sales Playbook.pdf"
if pdf.exists():
    st.sidebar.markdown(
        f'<a href="data:application/pdf;base64,{base64.b64encode(pdf.read_bytes()).decode()}" '
        f'download="GreenPayroll_Playbook.pdf" style="text-decoration:none">'
        f'<div style="background:#28a745;padding:8px;border-radius:4px;text-align:center;color:white">'
        f'Download Sales Playbook</div></a>', unsafe_allow_html=True)

# Scenario selector
names = [f"{s['id']}. {s['prospect']} ({s['category']})" for s in SCENARIOS]
pick  = st.sidebar.selectbox("Choose a scenario", names)
voice = st.sidebar.checkbox("🎙️ Voice Playback")

S = SCENARIOS[names.index(pick)]

# ── Assess Difficulty Dynamically ──
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

# ── SYSTEM PROMPT ──────────────────────────────────
sys = f"""
You are **{P['persona_name']}**, **{P['persona_role']}** at **{S['prospect']}**.

Stay strictly in character using realistic objections & tone.

▼ Green Payroll facts you may reference:
• All-in-One Workforce Platform (payroll, benefits, time, onboarding)
• Dedicated Service Team (named account manager)
• Compliance Peace-of-Mind (proactive alerts)
• Seamless Integrations (QuickBooks, ERP, ATS)
• Typical client gains: save 4–6 h/wk, lower errors, scale without extra HR staff

▼ Common discovery questions you expect:
  “What system are you using now?” • “What challenges do you face?” •
  “How much time is payroll taking?” • “Are you confident in compliance?” •
  “What does success look like?”

▼ Preferred closing approaches:
  • Offer demo  • Offer free trial  • “Does this sound like a fit?”  • Next-step scheduling.

You have {P['time_availability']['window']} min for this call. End it if the rep wastes time.
"""

# ── SESSION STATE ─────────────────────────────────
if "scenario" not in st.session_state or st.session_state.scenario != pick:
    st.session_state.scenario = pick
    st.session_state.msgs = [{"role":"system","content":sys}]
    st.session_state.closed = False
    st.session_state.score = ""
    st.session_state.score_value = 0

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
if st.sidebar.button("🔄 Reset Chat"):
    st.session_state.clear(); st.rerun()

if st.sidebar.button("🔚 End & Score"):
    if not st.session_state.closed:
        total, fb, subs, feedback_detail = calc_score(st.session_state.msgs)
        st.session_state.closed = True
        st.session_state.score = f"🏆 **Score {total}/100**\n\n{fb}"
        st.session_state.sub_scores = subs
        st.session_state.feedback_detail = feedback_detail
        st.session_state.score_value = total
        st.sidebar.success("Scored!")

if st.session_state.score:
    # Add next meeting outcome narrative
    outcome_story = generate_follow_up_narrative(st.session_state.sub_scores, S, P)
    st.sidebar.markdown("### 📘 What Happened Next")
    st.sidebar.markdown(outcome_story)
    st.sidebar.markdown(st.session_state.score)
    if "sub_scores" in st.session_state:
        st.sidebar.markdown("### 🧩 Score Breakdown")
        for k, v in st.session_state.sub_scores.items():
            st.sidebar.write(f"{k.title()}: {int(v)}/20")
    if "feedback_detail" in st.session_state:
        st.sidebar.markdown("### 📣 Suggestions for Improvement")
        st.sidebar.markdown(st.session_state.feedback_detail)
    name = st.sidebar.text_input("Name:", key="nm")
    if st.sidebar.button("🏅 Save to Leaderboard") and name:
        cur.execute("INSERT INTO leaderboard(name,score,timestamp) VALUES(?,?,?)",
                    (name, st.session_state.score_value, datetime.datetime.now()))
        conn.commit()
    st.sidebar.write("### Top 10")
    for i,(n,s) in enumerate(cur.execute(
        "SELECT name,score FROM leaderboard ORDER BY score DESC,timestamp ASC LIMIT 10"),1):
        st.sidebar.write(f"{i}. {n} — {s}")
