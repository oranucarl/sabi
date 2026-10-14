# SAbi demo script (about 4 minutes)

**Persona:** Chiamaka, SS3 student in Lagos, preparing for WAEC and JAMB on a shared laptop with
unreliable data.

## Before you start
- Ollama is running and `qwen2.5vl:7b` has been used once (warm), so the first answer is fast.
- SAbi is running, and Microphone, Screen Recording and Input Monitoring are granted.
- Have open: a past-question PDF with a quadratic-equation question, and a short physics notes PDF on
  waves (not yet added to SAbi).
- Fresh journal: `SABI_DATA_DIR=/tmp/sabi-demo .venv/bin/python -m sabi`
- To prove "offline", turn Wi-Fi off before scene 2 and set `SABI_TTS=say`, or keep Wi-Fi on for the
  Nigerian neural voice and mention it falls back automatically.

## 1. The problem (30 s, slide or spoken)
"Many students start a learning journey and quietly fall off. Help costs money, needs data, and
assumes standard English. Chiamaka has a laptop, past questions, and no tutor."

## 2. Ask about the screen (60 s)
1. Open the past-question PDF. Hold **⌃⌥**: *"How do I solve this question?"*
2. SAbi points at the equation and starts step 1. Say *"next"* twice.
3. **Point to make:** this runs fully on the laptop with no internet. The model, speech and voice are all local.

## 3. Pidgin (30 s)
1. Hold **⌃⌥**: *"Abeg explain am for Pidgin, I never understand."*
2. SAbi switches to Pidgin with a Nigerian voice.
3. **Point to make:** learners use the language they actually think in. It also supports French,
   Portuguese, Arabic and Swahili, plus a typed mode for noisy rooms or learners who can't speak.

## 4. Trustworthy answers from her own notes (45 s)
1. Drag the physics notes PDF onto the SAbi panel.
2. Hold **⌃⌥**: *"What is the difference between transverse and longitudinal waves?"*
3. The panel shows **Sources: [1] Physics notes, p. 2**.
4. **Point to make:** answers are traceable to the learner's own materials, page by page. SAbi says
   when the notes don't cover something.

## 5. Staying in the journey (45 s)
1. Say *"Quiz me."* SAbi asks a question on something she studied earlier.
2. Answer out loud (get it partly wrong on purpose).
3. SAbi grades it against the correct answer from her notes, explains, and schedules the next review.
4. **Point to make:** spaced repetition (SM-2) turns one-off questions into long-term memory.

## 6. Where it leads (30 s)
1. Say *"What should I learn next?"*
2. The panel shows what's going well, what to review, the next WAEC/NECO syllabus topics, free
   resources, and opportunities (JAMB, WAEC, 3MTT, ALX).
3. **Point to make:** every link comes from a curated list of official, free resources; the AI never
   invents them.

## 7. Close (20 s)
"SAbi is free, works offline, and keeps everything on the device. Today it runs on Apple Silicon
Macs. Next: Windows, then a school 'SAbi box' that serves cheap laptops and phones over local
Wi-Fi."

## Backup plan
- If voice fails, type the same questions in the panel.
- If pointing misses, the spoken explanation still works. Mention that a cloud key can be added for
  more precise pointing.
- Keep a screen recording of a good run in case the live demo fails.
