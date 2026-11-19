from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN

BG=RGBColor(0x0f,0x17,0x2a); CARD=RGBColor(0x1e,0x29,0x3b); WHITE=RGBColor(0xf8,0xfa,0xfc); MUTED=RGBColor(0xcb,0xd5,0xe1)
PURPLE=RGBColor(0xa7,0x8b,0xfa); GREEN=RGBColor(0x34,0xd3,0x99); RED=RGBColor(0xf8,0x71,0x71); AMBER=RGBColor(0xfb,0xbf,0x24); BLUE=RGBColor(0x38,0xbd,0xf8)
prs=Presentation(); prs.slide_width=Inches(13.333); prs.slide_height=Inches(7.5)
blank=prs.slide_layouts[6]

def slide():
    s=prs.slides.add_slide(blank); bg=s.background.fill; bg.solid(); bg.fore_color.rgb=BG; return s
def text(s,x,y,w,h,t,size=20,color=WHITE,bold=False,align=PP_ALIGN.LEFT):
    tb=s.shapes.add_textbox(Inches(x),Inches(y),Inches(w),Inches(h)); tf=tb.text_frame; tf.word_wrap=True
    lines=t if isinstance(t,list) else [t]
    for i,l in enumerate(lines):
        p=tf.paragraphs[0] if i==0 else tf.add_paragraph(); p.alignment=align
        r=p.add_run(); r.text=l; r.font.size=Pt(size); r.font.color.rgb=color; r.font.bold=bold; r.font.name="Calibri"
        p.space_after=Pt(8)
    return tb
def card(s,x,y,w,h,title,body,accent,size=16):
    sh=s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE,Inches(x),Inches(y),Inches(w),Inches(h))
    sh.fill.solid(); sh.fill.fore_color.rgb=CARD; sh.line.color.rgb=accent; sh.line.width=Pt(2.5); sh.adjustments[0]=0.08
    text(s,x+0.25,y+0.18,w-0.5,0.6,title,22,accent,True)
    text(s,x+0.25,y+0.85,w-0.5,h-1,body,size,MUTED)
def header(s,kicker,title,color=PURPLE):
    text(s,0.6,0.35,12,0.5,kicker.upper(),14,color,True); text(s,0.6,0.75,12.2,1,title,34,WHITE,True)

# 1 title
s=slide()
text(s,0.8,1.6,11.7,1.2,"🕰️ FreshBench",64,WHITE,True)
text(s,0.8,2.9,11.7,1,"Benchmarking AI agents on whether their answers are still true",30,MUTED)
text(s,0.8,4.3,11.7,1.4,["Bifrost track: Benchmarking Platform for AI Agents, Not Just Models","Tavily track (merged): Stale-Answer Detector"],20,PURPLE,True)
text(s,0.8,6.2,11.7,0.6,"Built with Bifrost by Maxim AI  ·  Tavily Search API  ·  Python",16,MUTED)

# 2 problem
s=slide(); header(s,"The problem","LLM agents confidently repeat facts that used to be true",RED)
card(s,0.6,2.0,3.9,2.4,"Training cut-off","Models answer from a frozen snapshot: last year's champion, a former CEO, an old library version, last quarter's rate.",RED)
card(s,4.7,2.0,3.9,2.4,"Benchmarks rot too","Static gold answers go stale the moment the world changes, so today's leaderboards can't measure freshness.",AMBER)
card(s,8.8,2.0,3.9,2.4,"Models ≠ agents","Accuracy alone ignores what teams actually pay for: cost, latency, provider failures, retries.",BLUE)
text(s,0.6,4.9,12,1.5,["A stale answer is worse than no answer: it looks right, ships to users, and erodes trust.",
  "Nobody measures how often agents are out of date, or what it costs to keep them current."],20,WHITE)

# 3 solution
s=slide(); header(s,"The solution","FreshBench = Stale-Answer Detector + agent benchmark",GREEN)
card(s,0.6,2.0,6.0,4.6,"🔎 Stale-Answer Detector",["1. Split an answer into atomic claims; flag the time-sensitive ones",
 "2. Neutral Tavily query per claim (never presupposes the answer)","3. Judge each claim against dated evidence: fresh / stale / incorrect / unverifiable, with citations",
 "4. Auto-repair: rewrite with current facts + 'as of' date","Works standalone as a guardrail for any AI app"],GREEN,17)
card(s,6.8,2.0,5.9,4.6,"🏆 Agent benchmark",["30 time-sensitive tasks, no frozen gold answers, so the benchmark never rots",
 "Same model inside different agent designs: closed_book · search_rag · guarded","Fixed judge scores every answer live",
 "Leaderboard: fresh rate, stale rate, cost per fresh answer, latency, tokens, fallbacks, errors"],AMBER,17)

# 4 architecture
s=slide(); header(s,"Technical architecture","Every LLM call via Bifrost, every fact checked with Tavily")
s.shapes.add_picture("docs/architecture.png",Inches(1.37),Inches(1.7),height=Inches(5.5))

# 5 bifrost
s=slide(); header(s,"How Bifrost contributes","Bifrost turns a model eval into an agent benchmark",PURPLE)
card(s,0.6,2.0,3.0,4.4,"🔀 One API","Agents and judge use provider/model ids (Groq, Gemini, OpenAI, Anthropic). Adding a model to the benchmark = one line.",PURPLE)
card(s,3.75,2.0,3.0,4.4,"🔑 Governance","Auto-generated config with a virtual key (x-bf-vk) restricting FreshBench to approved providers/models. Bad key → 401.",PURPLE)
card(s,6.9,2.0,3.0,4.4,"🛟 Reliability","Fallback chains handled by the gateway. FreshBench reads routing headers and counts fallbacks per agent.",PURPLE)
card(s,10.05,2.0,2.7,4.4,"⏱ Telemetry","Provider used, resolved model, gateway/upstream latency, tokens: these become the leaderboard's cost and latency columns.",PURPLE)
text(s,0.6,6.6,12,0.6,"Verified against the real maximhq/bifrost container: 48 agent runs, VK enforcement, OpenAI→Groq automatic fallback, 0 errors.",15,MUTED)

# 6 tavily
s=slide(); header(s,"How Tavily contributes","Tavily is FreshBench's source of current truth",GREEN)
card(s,0.6,2.0,4.0,4.4,"Evidence for the judge","One advanced search per time-sensitive claim, topic-routed (news / finance / general). URLs + publish dates let the judge prefer the newest source.",GREEN)
card(s,4.75,2.0,4.0,4.4,"Grounding for agents","search_rag answers from Tavily results; the guarded agent uses Tavily evidence to repair stale drafts with citations.",GREEN)
card(s,8.9,2.0,3.8,4.4,"Priced into the score","Tavily credits are part of each agent's cost → cost per fresh answer. 6h cache so agents never pay twice for the same query.",GREEN)

# 7 demo
s=slide(); header(s,"Working prototype","Streamlit dashboard + CLI",BLUE)
s.shapes.add_picture("docs/detector.png",Inches(0.6),Inches(1.9),width=Inches(5.9))
s.shapes.add_picture("docs/leaderboard.png",Inches(6.8),Inches(1.9),width=Inches(5.9))
text(s,0.6,6.8,12,0.5,"Screenshots from offline simulation mode (fictional world). Live mode uses Bifrost + Tavily with real models.",13,MUTED)

# 8 metrics + validation
s=slide(); header(s,"Measuring what matters","Metrics & trust in the judge",AMBER)
card(s,0.6,2.0,6.0,4.6,"Leaderboard metrics",["Fresh rate: answers verified current today","Stale rate: answers with outdated/contradicted claims",
 "Cost per fresh answer: LLM (Bifrost) + Tavily","Latency · tokens · fallbacks · error rate",
 "FreshScore = 100·fresh·(1−err) − 50·stale"],AMBER,17)
card(s,6.8,2.0,5.9,4.6,"Judge you can trust",["Fixed judge model for every agent = fair comparison","Calibration set: known-stale + evergreen controls → precision/recall",
 "Stale ≠ incorrect: superseded vs hallucinated","Unverifiable is reported, never hidden","13 automated tests incl. a live-Bifrost test"],BLUE,17)

# 9 next
s=slide(); header(s,"What's next","From benchmark to production guardrail",GREEN)
text(s,0.6,2.0,12,4,["• Ship the detector as a Bifrost plugin: flag or repair stale responses inline at the gateway",
 "• Continuous runs: re-score agents weekly and chart how fast each one goes stale",
 "• Freshness-aware routing: send time-sensitive questions to grounded agents, evergreen ones to cheap closed-book models",
 "• Community task packs (finance, sports, dev tooling) and public leaderboard"],22,WHITE)
text(s,0.6,6.3,12,0.8,"🕰️ FreshBench: because \"correct\" has an expiry date.",24,PURPLE,True)
prs.save("docs/FreshBench_Pitch_Deck.pptx"); print("saved")
