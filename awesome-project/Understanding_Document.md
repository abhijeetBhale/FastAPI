# Understanding Document — AI Cargo Detection & Lifting Plan Support
### In Simple Words, For Everyone (No Technical Knowledge Needed)

> Reference: this guide explains `docs/Final_Working.md` in everyday
> language. If you understand this document, you understand what the
> system does, why it works that way, and what to be careful about —
> without needing to know anything about software.

---

## 1. The Big Idea in One Minute

Imagine a crane is holding a big net full of material — hanging in the air.
Before lifting it further, someone must answer: *what is it, how big is it,
how heavy is it, and how should we lift it safely?*

Today, a person looks at it, guesses, measures manually, and fills a paper
form called a **lifting plan**.

Our system helps with that homework:

1. You take 1–3 ordinary photos of the hanging load with a phone.
2. The system looks at the photos, finds the load, outlines only the
   material (not the net, ropes, hook, or crane), and measures it.
3. It gives you a marked photo + a simple report: size, volume, estimated
   weight, and how sure it is.
4. It also prepares a **first draft** of the lifting plan — filling only
   what it actually saw or could fairly estimate, leaving the safety
   decisions empty for your engineer.

**Golden rule repeated everywhere in this project:**

> The system reports what it saw and suggests a starting point. It never
> decides if a lift is safe. A person always decides and signs off.

Think of it like a helpful junior assistant who measures and fills the
easy boxes, but never signs the final paper. The senior engineer always
checks and signs.

## 2. Who Is This For and How Each Person Uses It

### 2.1 Site worker with a phone (captures photos)

- Opens the dashboard or handheld app, selects the cargo type
  (for example coal, grain, sand).
- Takes 1–3 clear photos of the hanging load.
- Uploads them with a short note (for example "morning shift, load 2").
- Gets back: original photo + marked photo showing what was found,
  plus size and weight estimate.

Simple analogy: like scanning a parcel to get its size and postage —
you take a photo, the system measures the box.

### 2.2 Supervisor / reviewer (checks the work)

- Sees a list of all uploads: who sent what, when, and current status
  (draft, submitted, approved, rejected).
- Opens any item to see both photos side by side, the measurements,
  and how confident the system is.
- Approves it or sends it back with a comment.

### 2.3 Lifting engineer (owns safety)

- Receives the draft lifting plan with easy fields already filled.
- Checks the estimates, corrects them if needed, and fills the safety
  fields only they can fill (crane choice, method, capacity).
- Signs off. Until they sign, it is only a draft — never a permission
  to lift.

### 2.4 Manager / office (record keeping)

- Sees history: every photo, every measurement, every approval.
- Can compare loads over time and keep proof for audits.

## 3. How It Works — Told Like a Story

Think of 7 helpers passing a photo along a table:

| Step | Helper | What they do, in plain words |
|------|--------|------------------------------|
| 1. Select | You | Pick 1–3 photos of the hanging load. |
| 2. Quality check | The picky friend | Says "this one is too blurry / too dark / too small, take another." |
| 3. Find the load | The spotter | Points: "the load is here, in the lower part of the photo." Ignores tiny dots. |
| 4. Separate | The tracer | Draws neatly around only the solid material. Leaves out net, straps, chain, hook, crane. |
| 5. Measure | The measurer | Uses one known size (for example pallet width) as a ruler to work out real size, volume, weight. |
| 6. Check | The honest judge | Asks "am I really sure?" If yes, passes it on. If no, says "I found nothing confident" instead of guessing. |
| 7. Report | The clerk | Makes a marked photo + short summary and files it for review. |

Why separate the material from the net? Because we want to weigh the
contents, not the bag. If you weigh a sack of rice, you do not include
the truck carrying it. Same logic here.

## 4. What the System Fills In the Lifting Plan (and What It Leaves Empty)

A lifting plan is a safety paper. A wrong number there is dangerous.
So the system follows one strict rule:

> Seen = write it. Calculated with a clear assumption = write it with a
> label. Needs human judgement = leave it blank.

### 4.1 It safely fills what it SAW (like an eyewitness)

- What the load looks like and how many pieces there are.
- Where each piece is in the photo.
- How full the net looks.
- How sure it is (confidence score).
- Whether the load touches the photo edge (warning that part may be cut).

This is reporting, not guessing — like saying "I saw 3 boxes."

### 4.2 It estimates what it can CALCULATE (always labelled ESTIMATE)

With one known ruler (for example "this pallet is 1.2 m wide") it can
estimate real size, then weight (size x typical density of that cargo).

- Every such number carries **[ESTIMATE]** next to it plus the assumption
  ("assumes pallet = 1.2 m, coal density = X").
- It also adds a "what I observed" note and a "suggested starting point"
  (for example suggested sling), clearly marked as suggestion only.

Analogy: if you know one tile is 1 foot wide, you can estimate room size
by counting tiles — but you still write "approx."

### 4.3 It sketches theoretical rigging geometry (labelled THEORETICAL)

It can suggest where the balance point and hook might be, assuming weight
is evenly spread and a standard two-leg sling is used.

- Each value is marked **[THEORETICAL]** with assumptions written beside it.
- Your engineer treats it like a pencil sketch: adjust to real equipment,
  confirm the angle, approve or correct. Starting from a sketch is faster
  than starting from a blank page.

### 4.4 It MUST leave safety decisions BLANK (for your engineer only)

| Left blank | Why, in simple words |
|------------|----------------------|
| Single or tandem lift method | The photo shows a load, not your site plan. |
| Routine or non-routine lift | Your procedure and risk review must classify it. |
| Crane, boom, radius, counterweight, capacity | These belong to the specific crane on site, not visible in a photo. |
| Which gear to use, safety factors | Can only be chosen once crane + method + weight are known. |

> An invented number on a safety paper is worse than a blank space.
> A blank space asks for thought. A fake number invites false trust.

## 5. How Reliable Is It? (Quality in Plain Words)

| Promise | What it means for you |
|---------|-----------------------|
| Trained on your real loads | It learned from photos of nets and pallets like yours, not random internet pictures. |
| Checks itself before answering | A result is only shown if it passes built-in quality gates. |
| Honest when unsure | Says "no confident cargo found" rather than making up a number. |
| Keeps working if a part fails | If the specialist recogniser is down, a general one steps in so work continues. |
| Never hides that it estimated | Every estimate shows its label and assumption. |
| Human sign-off built in | Draft stays draft until your engineer approves. |

Think of a weighing scale that either shows the true weight or clearly
says "unstable — try again" instead of showing a random number. That is
how this system behaves.

## 6. Assumptions — What We Take For Granted, and Why

> An assumption is something the system believes without checking live.
> Each one below says WHAT we assume, WHY (reasoning), WHAT GOES WRONG
> if false, and WHAT YOU can do. This is the safety net — read carefully.

### A1. One known reference size is given correctly

- **Assume:** Someone provides one true size in the photo
  (for example pallet = 1.2 m wide).
- **Why:** A photo has no ruler. Without one known length the system only
  knows bigger/smaller on screen, not metres. Like counting floor tiles —
  you must first know one tile's size.
- **If wrong:** All later numbers scale wrongly. 10% ruler error means
  about 30% volume/weight error (volume grows in 3 directions).
- **Do this:** Measure once carefully, mark it, reuse same object.

### A2. Weight is an estimate, never a certified figure

- **Assume:** Weight = measured volume x typical density of that cargo.
- **Why:** A camera cannot weigh. It sees shape and looks up how heavy
  that material usually is. Wet vs dry, packed vs loose all differ.
- **If ignored:** Someone may overload a crane trusting the number.
- **Do this:** Keep the [ESTIMATE] label; verify with a scale for
  critical lifts.

### A3. Depth is guessed from a single photo

- **Assume:** How far back the load goes is inferred from shading/shape.
- **Why:** One photo is flat. Depth must be reconstructed, so it is less
  certain than width/height seen directly.
- **Do this:** For odd shapes, take two sides or measure manually.

### A4. First photo is the main one

- **Assume:** When several photos are given, detailed numbers come from
  photo 1; others are context.
- **Why:** Anchoring to one image keeps the report simple and comparable
  instead of mixing views.
- **Do this:** Put your best, front-facing, well-lit photo first.

### A5. Weight is cargo-as-seen, net/pallet included

- **Assume:** The estimate covers the visible body; it does not subtract
  net, straps, or pallet, nor fill hidden hollows.
- **Why:** The system cannot weigh the net separately from a photo, and
  cannot see inside. Subtracting unseen tare would be fake precision.
- **Do this:** Weigh net/pallet once separately; engineer subtracts tare.

### A6. Load hangs freely and is mostly fully visible

- **Assume:** Load hangs in air, not on ground, not heavily cropped or
  hidden behind people/equipment.
- **Why:** The finder expects a suspended shape in the lower image area.
  Ground contact or cropping breaks that.
- **Do this:** Stand back, include full load with margin, avoid cut edges.

### A7. Photos are clear, lit, large enough

- **Assume:** Not too blurry, dark, or tiny.
- **Why:** Edges, shading, and texture are needed. Bad input gives an
  honest no-result, not a miracle.
- **Do this:** Use light, hold steady, focus, fill quarter frame with load.

### A8. Balance point assumes even weight + standard sling

- **Assume:** For the balance/hook sketch, weight is uniform and sling is
  a standard two-leg type.
- **Why:** The photo shows outer shape, not inner distribution. Uniform is
  the only neutral starting guess without opening the net.
- **If lopsided:** True balance shifts.
- **Do this:** Engineer adjusts for uneven loads and real gear. That is why
  it is marked THEORETICAL.

### A9. Operator picks the correct cargo type

- **Assume:** The uploader selects the right material so the right typical
  density is used.
- **Why:** Coal vs sand vs scrap differ hugely; the camera cannot reliably
  tell them apart inside a net.
- **Do this:** Double-check the dropdown; ask supervisor when unsure.

### A10. Density is typical, not lab-measured per load

- **Assume:** Catalogue average is enough for a draft.
- **Why:** Moisture and packing vary; testing every load defeats a quick
  draft.
- **Do this:** For critical lifts, replace with a sampled measurement.

### A11. Fallback recogniser is general, not specialised

- **Assume:** If the cargo-tuned model is down, a general one keeps work
  going with slightly less tuned results.
- **Why:** A slightly weaker result today beats no result on site.
- **Do this:** Treat fallback with extra caution; re-run later if possible.

### A12. People own crane, method, and go/no-go

- **Assume:** Site supplies crane specs, chooses method, classifies the
  lift, and authorises.
- **Why:** Those depend on equipment, ground, weather, procedures — none
  visible in a load photo.
- **Do this:** Never ask the system for these; keep blank till engineer
  fills them.

### A13. Storage and upkeep are ongoing

- **Assume:** Photos, reports, history need hosting, backup, retraining
  for new cargo.
- **Why:** History proves compliance and improves the system, but needs
  disk and care.
- **Do this:** Budget for hosting + storage + maintenance, not just setup.

## 7. What It Costs Over Time (Plain Words)

One-time setup is only the start. To keep it running you need:

- A place to keep the website + database running (hosting).
- Computer time for photo analysis (heavier work needs stronger machines).
- Space for photos, reports, and history (storage grows every day).
- Updates and help when things change (maintenance).
- Re-learning when new cargo types appear (a few example photos).
- App-store accounts if the handheld app is distributed that way.

Good news from the reference doc: the AI pieces themselves are
open-source, so there is **no per-photo AI bill**. You pay for computers
and care, not per click.

## 8. Timeline

An indicative timeline lives in the shared planning sheet and is firmed
up after a short discovery of final scope:

[AI-Cargo-Project-Timeline](https://docs.google.com/spreadsheets/d/1cFk0qRtuzduAzVEXRNuuwc5FzKoXi0fjxX9oodNa39M/edit?usp=sharing)

## 9. Common Questions (FAQ)

**Do I need a special camera?**
No. An ordinary phone works. Clarity and light matter more than brand.

**Does it work in the dark or rain?**
Poorly — like human eyes. Light it well and wipe the lens.

**Can it certify the weight?**
No. It estimates. Only a scale certifies. Treat it as a fast draft.

**Will it pick my crane?**
Never. Your engineer picks the crane, method, and whether to lift.

**What if it finds nothing?**
That is a valid, honest answer. Retake the photo with better framing
and light, and try again.

**What if I disagree with a measurement?**
You are supposed to check. Correct it, note why, and sign. Your judgement
overrules the draft.

## 10. One-Page Summary to Remember

1. Photo in -> marked photo + measurements + draft plan out.
2. Seen things are reported; calculated things are labelled ESTIMATE /
   THEORETICAL; safety decisions stay blank.
3. A wrong reference size, wrong cargo type, or bad photo = wrong estimate.
4. Weight is always an estimate, never a scale reading.
5. A blank safety field is safer than a guessed number.
6. A person always decides and signs. The system only helps.

---

*End of Understanding_Document.md — companion to docs/Final_Working.md*








