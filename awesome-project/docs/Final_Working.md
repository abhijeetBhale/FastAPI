# **AI Cargo Detection & Lifting Plan Support**
## From a Photo of a Hanging Load to a Checked Lifting-Plan Draft

# **1. What the System Does**

Using ordinary photos or videos, the system automatically recognises the
hanging cargo load, separates the cargo itself from the net, straps, chain,
hook and crane around it, and measures it. From that measurement it
estimates the load's size, volume and weight, and saves the result as a
simple inspection report.

The same results feed a **draft lifting plan**: the system fills in what it
has observed and what it can calculate from clearly stated assumptions, and
leaves the judgement calls to your engineer.

The guiding principle throughout: **the system reports what it saw and
suggests a starting point. It never decides the crane, the lifting method,
or whether a lift is safe. A person always decides and signs off.**

**How it works, end to end:**

| Stage | What happens |
| :---- | :---- |
| Select | Pick one to three photos |
| Quality check | Notes if a photo is too blurry, too dark or too small |
| Find the load | Locates the suspended cargo in the photo |
| Separate | Distinguishes the solid cargo from net, straps, chain, hook and crane |
| Measure | Works out the load's dimensions, volume and estimated weight |
| Check | Confirms the result is trustworthy — or honestly reports that it found nothing |
| Report | Produces a marked-up image and a summary your team can review |

## **1.1 What the AI may write on the lifting plan**

| The AI does | The AI never does |
| :---- | :---- |
| Reports what it observed — what it found, how many items, how confident it is | Choose the crane, radius, boom or counterweight |
| Estimates size and weight from a known reference size, clearly marked as an estimate | Decide the lifting method, or whether the lift is routine or non-routine |
| Calculates a theoretical rigging geometry with its assumptions stated next to it, clearly marked | Fill in any field that requires engineering judgement |
| Says honestly when it finds nothing | Invent a plausible-looking number for a safety document |

An invented number on a safety document is worse than a blank space.

# **2. The Technology Behind It**

Built entirely with well-established, open-source AI tools — no per-use
licence fees, and nothing here locks you into a single vendor.

| Layer | What is used | Its role in this project |
| :---- | :---- | :---- |
| Vision AI | Proven open-source image-recognition models | Finds the cargo in the photo |
| Image outlining | Open-source segmentation models | Traces the exact shape of the cargo, excluding rigging |
| Depth sensing | Open-source single-image depth AI | Estimates how far back the load extends, from one photo |
| Measurement | Standard 3D geometry from the outlined shape | Turns the outline into size, volume and weight estimates |
| Backend | A standard web service and database | Stores cargo records and lifting-plan history |
| Front end | Web dashboard and Android handheld app | Where your team captures photos and reviews results |

**Trained for your cargo:** the recogniser was refined on real images of
cargo in nets and on pallets, so it is tuned to your kind of loads rather
than a generic model. If the specialist model is ever unavailable, the
system automatically falls back to a general-purpose recogniser so it keeps
working.

# **3. How the Pipeline Works, Step by Step**

## **3.1 Finding the load**

The system scans the photo for suspended cargo and classifies what it
finds: the solid cargo itself, the whole netted load (used as a back-up
guide), and the rigging gear that must be ignored. It applies common-sense
checks — the load must sit in the lower part of the image, not float near
the top; tiny specks are not cargo. If nothing looks like a real load, it
says so rather than guessing.

## **3.2 Separating cargo from rigging**

Using the found location as a guide, the outlining model traces only the
solid cargo body. The net, straps, chain, hook and crane are explicitly
excluded, so the measurement reflects the cargo — not the gear around it.

## **3.3 An honest confidence check**

Every result is scored. If the result is confident, it proceeds. If not,
the system reports **"no confident cargo found"** instead of returning a
number it cannot stand behind. On clear photos it consistently identifies
the full load; edge cases (a sliver of load touching the frame edge) are
detected and reported rather than silently accepted.

## **3.4 Measuring — size, volume, weight**

One known size on site (for example, the width of a pallet) is used as a
reference to convert the photo into real-world measurements. From the
cargo's outlined shape, the system works out its dimensions and approximate
volume, then combines that with the known density of the cargo type to
estimate the weight. Every estimate is labelled as an estimate.

## **3.5 The report**

Each run produces a marked-up image (what was found, what was excluded)
and a plain summary: dimensions, estimated weight, and how confident the
system is. Results are saved so your team can review, compare and share
them.

# **4. What the AI Fills in the Lifting Plan — and What It Must Not**

The lifting plan is a safety document. This section answers a simple
question: **which fields can the system reasonably fill in, and which must
be left for your engineer?**

The rule: the system fills in what it *observed* and what it can *calculate
from clearly stated assumptions*. It never invents what requires
engineering judgement, site knowledge, or a crane's own specifications.

## **4.1 What it observed (safe to fill automatically)**

It saw this in the photo — filling it in is reporting, not guessing.

| Field | Where it comes from |
| :---- | :---- |
| Description of the load | What the system found in the photo |
| Number of items | Counted in the photo |
| Location and size of each item | Marked on the photo |
| How confident the system is | Its own confidence score |
| How full the load is | Cargo area compared with the netting area |
| Whether the load touches the edge of the photo | Checked automatically |
| Overall size on screen | Measured from the photo |

## **4.2 What it can estimate (with a known reference, clearly labelled)**

The system cannot measure these directly, but it can produce a
**clearly-labelled estimate** once the site supplies one known size (for
example, the pallet width).

| Field | What it needs | What you get |
| :---- | :---- | :---- |
| Real-world dimensions | One known reference size | An estimate, marked as such |
| Weight estimate | Dimensions + the cargo type's typical density | An estimate, marked as such |
| Cargo type | Chosen by the operator | Looks up the typical density |

Everything in this category is tagged **[ESTIMATE]** and always shows the
assumption behind it. The draft plan also includes a short **"what the AI
observed"** note and a **"suggested starting point"** — for example, an
estimated weight and a sling suggestion — clearly presented as a starting
point for review, never as a certified answer.

## **4.3 Theoretical rigging geometry (clearly marked, with assumptions)**

The system also calculates a *theoretical* centre of gravity and hook
position based on the shape of the load — assuming the weight is evenly
distributed and a standard two-legged sling is used.

Every one of these values is:

* marked **[THEORETICAL]**,
* shown with its assumptions written next to it (weight evenly
  distributed; standard two-leg sling; sling length adjustable to your
  equipment; hook centred over the load), and
* presented as a starting point for your engineer to confirm or correct —
  **not as certified rigging parameters**.

Your engineer can react to it the way they would react to a sketch: adjust
the sling to the equipment actually available, confirm the angle, and
approve or correct it. The value is that they start from a considered
hypothesis instead of a blank box.

## **4.4 What must stay blank (engineering judgement)**

The system cannot know these. Filling them would be **making something
up** — a plausible-looking number with no real basis. On a safety
document, that is worse than leaving it blank.

| Field | Why the system can't know it |
| :---- | :---- |
| Lifting method (single or tandem) | A site decision — the photo shows a load, not your lift plan |
| Routine or non-routine lift | A classification your procedure and risk assessment must decide |
| Counterweights, boom, working radius | Properties of the specific crane — not visible in a photo |
| Lifting capacity | Depends on the crane and how it will be set up on site |
| Which lifting gear to use | Depends on your equipment, the method, and the (estimated) weight |
| Safety factors and load percentages | Calculated only once the crane and gear are chosen |

**In short:** what it *saw* is reported. What it can *calculate* is
estimated and labelled. What needs *judgement* belongs to your engineer.

# **5. Quality & Reliability**

The system is built so that its results can be trusted — or honestly
questioned:

| Principle | What it means for you |
| :---- | :---- |
| Trained and checked on real cargo photos | Tuned to your kind of loads, not a generic demo |
| Automatic self-checks before any result is used | Runs are only accepted if they pass built-in quality checks |
| Honest when unsure | Says "no confident cargo found" rather than guessing |
| Keeps working if a component is unavailable | Falls back to a general recogniser and still produces a result |
| Never silent about estimates | Every estimated figure is labelled and shows its assumption |
| Human sign-off built in | The draft is a draft until your engineer approves it |

# **6. Assumptions & Limitations**

1. Real-world sizes depend on one known reference size being given
   correctly — if the reference is wrong, the measurements and weight are
   wrong with it.
2. Depth and volume are estimated from a single photo, so weight is a
   well-informed estimate, **not a certified figure**.
3. When several photos are provided, the detailed report describes the
   first one.
4. The estimated weight is for the cargo as seen — it does not subtract
   the weight of the netting or pallet itself.
5. Open points to confirm with your team: how the sling suggestion should
   be tuned to your equipment, and how the finished draft should be laid
   out to match your paper form.

# **7. Timeline**

An indicative timeline is kept in the shared sheet and gets firmed up
after a short discovery pass over the final scope:

[AI-Cargo-Project-Timeline](https://docs.google.com/spreadsheets/d/1cFk0qRtuzduAzVEXRNuuwc5FzKoXi0fjxX9oodNa39M/edit?usp=sharing)

# **8. Ongoing / Recurring Cost Considerations**

* Hosting for the backend and database, plus GPU time if image processing
  runs there.
* App store developer accounts (Google Play, and Apple if iOS is added).
* Storage for photos, readings, plans and approval history.
* Retraining whenever new cargo types appear.
* Maintenance — updates, upgrades, and support.

Because the AI stack is open-source (§2), there is **no per-use AI bill**
in the running system — the recurring costs are infrastructure and upkeep,
not model calls.