# SAbi Tutor

**A free, offline, voice-first tutor that sits beside any learning tool a student already has.**

*"Sabi"* is Nigerian Pidgin for *to know*. A "sabi person" is someone who knows their stuff.

Hold a key, ask out loud, in English or Pidgin, about whatever is on your screen: a maths question in a
past-paper PDF, an Excel formula, a confusing university portal. SAbi looks at your screen, answers by
voice, points at the exact spot, and teaches step by step. It remembers what you studied, quizzes you
later so it sticks, and shows you what to learn next and where it can lead.

## Why

Many learners across Africa start studying and quietly fall off: help is expensive, materials are
scattered, and most AI tutors assume fast internet, paid subscriptions and fluent standard English.
SAbi is built for the opposite conditions.

| Constraint | How SAbi responds |
|---|---|
| **Cost** | $0 to run locally through Ollama. Eligible Plus and Pro users can also connect an existing ChatGPT plan—no API key or separate API billing. |
| **Low bandwidth** | Works fully offline once models are downloaded. Online voices are optional and fall back to the built-in voice. |
| **Credible sources** | Answers from your own notes and past questions cite the document and page. Pathway links come only from a hand-curated list of official, free resources, never invented by the model. |
| **Literacy and accessibility** | Voice in, voice out, and pointing on screen, plus a typed mode for noisy rooms or learners who can't speak. |
| **Language** | Replies in Nigerian Pidgin, English, French, Portuguese, Arabic, Swahili and more, following the learner. Say *"abeg talk Pidgin"* to switch. |
| **Privacy** | Local mode keeps screenshots, voice, journal and documents on the device. ChatGPT mode clearly indicates that the current question, relevant note excerpts and any required screenshot are sent to OpenAI. Screenshots are skipped on banking, password and sign-in screens. |
| **Local relevance** | Pathways follow the WAEC/NECO syllabus order and point to JAMB, WAEC, 3MTT, ALX and other local opportunities. |

## What it does

- **Screen-aware answers:** hold **⌃ Control + ⌥ Option**, ask, release. SAbi sees the screen and answers.
- **Points at things:** the green buddy flies to the button, formula or word it is explaining.
- **Step-by-step lessons:** multi-step answers are taught one step at a time; say *"next"* or *"repeat"*.
- **Cited answers from your notes:** drop PDFs or text notes on the panel; answers cite them like `[1]`.
- **Spaced-repetition review:** every topic you ask about becomes a review card. Say *"quiz me"*;
  answer out loud; SAbi grades you and schedules the next review (SM-2).
- **Pathways:** say *"what should I learn next?"* to see what's going well, what to review, the next
  syllabus topics, free resources, and the exams and programmes it leads to.

## Run it (macOS 14+, Apple Silicon)

```bash
# 1. Local models (free; about 7 GB in total)
#    Install Ollama from https://ollama.com/download, then:
ollama pull qwen2.5vl:7b          # use qwen2.5vl:3b on 8 GB Macs
ollama pull nomic-embed-text

# 2. SAbi (Python 3.11 or 3.12)
python3.12 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/python -m sabi
```

On first run, macOS asks for **Microphone**, **Screen Recording** and **Input Monitoring** for the app
that launched SAbi (e.g. Terminal). Grant them in System Settings → Privacy & Security, then restart SAbi.

Optional: copy `.env.example` to `.env` to change models, pin a reply language, or add a Claude key
for more precise pointing.

### Use an existing ChatGPT plan

SAbi can use an eligible ChatGPT Plus or Pro plan without an OpenAI API key or separate API billing:

1. Open SAbi and click **Continue with ChatGPT**.
2. Approve plan usage in the browser.
3. Choose one of the models returned for your account from SAbi's **AI** menu.

SAbi uses OpenAI's public Responses API with `store: false`. Connecting does not give SAbi access to
your ChatGPT conversations. The renewable OAuth session is stored in
`~/Library/Application Support/Sabi/chatgpt-auth.json` with owner-only file permissions. Use
**Disconnect** to revoke the renewable session and erase the saved tokens. Model access and usage
limits are determined by the selected ChatGPT account.

Choose **Offline · Ollama** at any time to stop sending questions and screenshots to OpenAI. The
status below the AI selector always states whether SAbi is operating locally or through ChatGPT.

### Build the app

```bash
uv pip install --python .venv/bin/python pyinstaller
scripts/build_app.sh        # → dist/SAbi.app and dist/SAbi.dmg
```

The app bundles the Whisper speech model (run SAbi from source once first so it is downloaded) and is
ad-hoc signed. On another Mac, the first launch is blocked by Gatekeeper: open System Settings →
Privacy & Security and click **Open Anyway**. Ollama and its models are installed separately. The
installed app reads its settings from `~/Library/Application Support/Sabi/.env` and logs to
`~/Library/Logs/SAbi.log`.

## Limits and roadmap

This is a proof of concept. It needs a Mac with Apple Silicon and 16 GB of memory for the default local
model (8 GB works with the smaller model), which most learners don't have. Next steps:

1. **Windows build**: the design keeps all macOS code in `sabi/platform/macos/`.
2. **Low-spec and shared devices**: a school or library "SAbi box" running the models for many cheap
   laptops and Android phones on the local network.
3. **Better local languages**: speech recognition tuned for Pidgin, Yoruba, Hausa and Igbo.
4. **More curricula**: syllabus maps for other countries' exams.

## Credits

Inspired by [clicky-windows](https://github.com/Bitshank-2338/clicky-windows) and the original Clicky
concept of a cursor-side screen assistant. SAbi is an independent codebase.

## License

MIT. See [LICENSE](LICENSE).
