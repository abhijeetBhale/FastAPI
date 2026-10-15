# Your AI Cargo Inspection System


> **About This Document**
>
> This document has been prepared by our team based entirely on the information, requirements, and supporting materials you provided to us. That includes the lifting plan documents (HSE-F003 forms for the 40FT container lift using the M3 crane, and the boom lift using the M1 & M2 cranes), the safety and operational requirements you shared, and all the discussions and details exchanged during the course of this project.
>
> Everything written here reflects your real work, your real processes, and the system we have built specifically to support them. Nothing has been assumed or invented — it is all based on what you gave us.

---

## What Is This?

Every time a heavy load is lifted at your port, a safety form called a **lifting plan** must be filled in first. Right now, someone walks up to the load, measures it by hand, estimates the weight, and fills in the form from scratch. That takes time. The result depends entirely on who happens to be doing it that day.

We built a system that does most of that work automatically. Someone takes a photo of the load on a phone. The system measures it, estimates the weight, and prepares a ready-to-review draft of the lifting plan. Your engineer then checks the draft, makes any corrections, fills in the safety parts, and signs. Done.

| The Old Way | With This System |
|---|---|
| Measure the load by hand on site | Take a phone photo — measurement is done automatically |
| Estimate the weight from experience | Weight is estimated and clearly labeled as an estimate |
| Fill the lifting plan from a blank page | Lifting plan draft is prepared automatically |
| Paper records, easy to lose or misplace | Everything stored digitally, searchable anytime |
| Quality depends on who fills it in | Same clear format on every job, every shift |

---

## How It Works — Four Simple Steps

Your team does Step 1. The system does Steps 2 and 3. Your engineer does Step 4. That is the whole process.

**Step 1 — Take 1–3 photos of the load**

A worker on site takes clear photos of the load using an ordinary phone. The load should be resting on the ground with the full shape clearly visible. No special camera or equipment is needed.

**Step 2 — The system measures the cargo**

Automatically, the system finds the cargo in the photo and measures it. It identifies the load against the ground surface and measures it directly — focusing only on the cargo itself, not the surrounding environment. It then estimates the weight based on those measurements.

**Step 3 — A lifting plan draft is prepared**

The system fills in the parts of the lifting plan it can calculate — size, estimated weight, and a description of what it saw. Every estimated number is clearly marked as an estimate. The safety fields are left blank on purpose for the engineer to fill in.

**Step 4 — Your engineer reviews and signs**

The lifting engineer opens the draft, checks all the numbers, makes any corrections needed, reviews the pre-filled crane and safety details, and signs off. Until they sign, it is only a draft. It is never a permission to lift.

---

## The Most Important Thing to Understand

> **The system reports what it saw and gives you a starting point. It never says whether a lift is safe. A person always decides and signs.**

Think of it as a thorough assistant who fills in the easy parts of the form — but your engineer is the one who says whether the lift can happen.

Any field that needs a safety decision — *which crane to use, the method of lifting, whether the lift is routine or not, which rigging gear to select — is left blank in the draft. The engineer fills those in. It is designed that way on purpose.

***With that information provided up front, these fields can be pre-defined in the system so the AI fills them in correctly and works accordingly — without ever inventing them on its own.**

A blank safety field means the engineer thought about it. A made-up number would give false confidence. **Blank is safer than wrong.**

---

## Who Uses It — Four People, Four Clear Roles

**Site Worker**
Takes 1–3 photos of the load on the ground and uploads them. They get back a photo showing exactly what the system found, along with the measurements it took.

**Supervisor**
Sees a full list of all uploads — who sent what, when it was uploaded, and what status it is at. Can open any item to check the photos and measurements before approving or sending it back.

**Lifting Engineer**
Gets the draft lifting plan with the easy fields already filled in. Reviews it, makes any corrections, adds the crane and safety details, and signs off. Their signature is the final authority — nothing lifts without it.

**Manager / Office**
Has a complete, searchable history of every inspection — every photo, every measurement, every approval, and the name of who made each decision. Ready for audits or client requests at any time.

---

## What the System Does — and What Your Team Always Does

| System Does Automatically | Your Team Always Does |
|---|---|
| Finds the cargo in the photo and measures its size | Decides which crane to use and at what configuration |
| Estimates the weight based on size and cargo type | Selects the rigging gear and checks safety factors |
| Flags unusual things — poor photo, cargo cut off at edge | Decides if the lift is routine or requires special precautions |
| Fills in the measurable parts of the lifting plan draft | Reviews the draft, corrects numbers, fills in the safety fields |
| Stores every photo, measurement, and decision in a searchable record | Signs the lifting plan — the final go or no-go before any lift begins |

---

## What Goes Into the Draft Lifting Plan

The system fills in Parts 1, 2, and 3 automatically. Part 4 is always left blank — those fields belong to your engineer.

**Part 1 — What the System Directly Saw in the Photo**

These are facts from the image — not calculations, not estimates. The system reports the number of objects it found, where each one sits in the photo, how much of the frame is actual cargo versus netting, how confident it was in what it found, and whether any part of the load was cut off at the edge of the photo. These are observations, the same as a person saying "I saw three boxes in the lower half of the image."

**Part 2 — What the System Calculated from Measurements**

If a known reference size is provided — for example, "this pallet in the photo is 1.2 metres wide" — the system can work out the real dimensions of the load in metres and estimate the weight. These numbers are always marked as estimates in the document, and the assumption used to calculate them is written right next to the number so the engineer can see exactly where the figure came from.

**Part 3 — A Starting Sketch of the Rigging Geometry**

The system can draw a theoretical picture of where the centre of gravity would sit, where the hook would be, and what angles the slings would make — assuming weight is evenly spread and a standard two-leg sling arrangement is used. These are clearly marked as theoretical starting points, not certified rigging parameters. The engineer reacts to the sketch — confirming, adjusting, or replacing it with the actual site conditions.

**Part 4 — What Is Always Left Blank**

*The crane details, working radius, counterweights, boom length, gear selection, safety factor, and capacity percentage are never filled in. These require the specific crane on site, the load chart for that machine, and the exact ground conditions — none of which the system can see. Those fields are left blank as a clear signal that the engineer must act on them before any lift proceeds.

***With that information provided up front, these fields can be pre-defined in the system so the AI fills them in correctly and works accordingly — without ever inventing them on its own.**

---

## Assumptions — What the System Takes for Granted, and Why It Matters

Every system that works from a photo instead of a direct measurement has to make some assumptions. These are listed below so your team knows what they are, what happens if one of them is wrong, and what to do about it.

**1. Three real measurement from the site must be provided**

Without at least three known size in the photo — for example, "this pallet is 1.2 metres wide" — the system can only say that one thing is bigger or smaller than another on screen. It cannot convert that to metres. Every other dimension flows from this one starting point, so getting it right matters a great deal.

**2. Weight is calculated, not weighed**

The system multiplies the measured volume by the typical density of the selected cargo type. It is not a scale. The result is a useful estimate for preparing the draft — but for any lift where the exact weight is critical, the load should be verified on a calibrated scale before the final plan is signed.

**3. Depth is estimated from a flat photo**

A single photo is two-dimensional. The system estimates how deep the load goes — front to back — from its shape and shading. This is less reliable than the width and height, which are seen directly. For loads with an unusual or irregular shape, taking three photos from different angles will give a more accurate picture.

**4. The first photo is the main one**

When multiple photos are uploaded, all measurements come from the first photo. The others give useful context but are not used for the numbers. The clearest, most directly facing photo of the load should always be uploaded first.

**5. The cargo type selected at upload must be correct**

The system uses the cargo type chosen during upload to look up the typical density for the weight calculation. Coal, grain, scrap steel, and gravel weigh very differently from one another. If the wrong type is selected, the weight estimate will be wrong. The engineer should always check this before relying on the draft.

**6. Density is a catalogue average, not a laboratory figure**

The density values in the system are standard industry averages for each cargo type. Real cargo density varies depending on moisture content, how tightly it is packed, and the grade of the material. For a critical lift where weight tolerance is tight, the estimate should be replaced with a figure from a scale or a sampled measurement.

**7. The load rests on the ground and is fully visible**

The system expects to find a load resting on the ground, with the full shape visible and clear of obstructions. If the load is partly hidden behind equipment or people, or has its edges cropped by the photo frame, the measurements will not be reliable. The photo should show the whole load with some space around it.

**8. The weight estimate covers the cargo as seen — not the net or straps**

The system measures and weighs the cargo itself. It deliberately ignores the surrounding netting, straps, and chains. The weight of the rigging equipment is not included in the estimate. The engineer must account for the weight of the gear separately when selecting rigging and checking the total load on the crane.

**9. Centre of gravity is assumed to be at the geometric middle of the load**

The system places the centre of gravity at the exact middle of the measured box. This is the safest neutral starting point when nothing else is known. For cargo that is heavier on one side — machinery with a motor at one end, for example, or a load that is denser at the base — the real centre of gravity will be in a different position. The engineer must adjust it.

**10. The hook and sling sketch assumes a standard two-leg arrangement**

The rigging geometry in the draft assumes two sling legs attached at the top corners of the load, with the hook directly above the centre of gravity. This is a common and practical arrangement, but it is not the only one. If the actual rigging method is different, the angles in the draft will not apply and must be recalculated.

**11. Sling length is assumed to be twice the height of the load**

The draft uses a sling length equal to two times the height of the load as a starting calculation for the hook position and sling angles. This is an assumption, not a site measurement. If the slings available on site are a different length, the angles will be different. The engineer confirms or corrects this before rigging.

**12. A confidence score is always shown — and it matters**

Every result the system produces includes a confidence score showing how certain it was about what it found in the photo. A high score means the system was clear and confident. A low score means it was uncertain. The engineer should treat low-confidence results with extra caution and consider asking for a retake of the photo in better conditions.

**13. The system does not know which crane is on site**

The system has no access to crane catalogs, load charts, or site layouts. It cannot know which machine will be used, what its rated capacity is at a given radius, or where it will be positioned relative to the load. All fields that depend on this information — counterweights, boom length, working radius, lifting capacity — are always left blank.

**14. Safety factor and capacity percentage are always left blank**

These two figures can only be calculated after the crane has been selected, the working radius has been measured on site, and the rated capacity has been read from the crane's load chart. The system leaves them blank as a deliberate reminder that these are the engineer's responsibility and cannot be filled without that information.

**15. Every theoretical value has its assumptions written next to it**

Any figure the system computed from a model — the centre of gravity position, the hook point, the sling angles — has its assumptions written directly next to it in the draft. The engineer can read exactly what was assumed, check whether it matches the real site conditions, and correct any value that does not. Nothing theoretical is presented without its reasoning visible.

---
