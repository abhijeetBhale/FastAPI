## Technical Feasibility Assessment & Proposed Approach

# **AI-Based Cargo Identification & Lifting Assistance**

## 

# **1\. Executive Summary**

The solution can be built with the technology you proposed. The chosen stack (FastAPI, Python 3.12, PostgreSQL, SQLAlchemy, and React) is a good fit and does not limit the project in any way. The field-facing part is a mobile app (Android) built with React Native, so it stays within the same React skill set.

The real challenge is not the software. It is the nature of what any camera — including a phone camera — can actually measure from an image:

* Material/type of cargo can be identified from images with good reliability.  
* Dimensions (size) cannot be measured exactly from a single flat photo, but can be estimated using a size reference already in the picture (for example, the standard pallet).  
* Weight cannot be measured from an image at all. It can only be estimated as a range, because weight depends on density, which a camera cannot see.

Because this system supports a safety-critical lifting operation, we recommend a practical and honest design: the AI gives an estimate with a confidence range; this is checked against the shipping documents (manifest) where available, and a human lifting supervisor gives the final approval. The AI assists the team; it does not replace their judgment.

We recommend delivering in phases, starting with a small proof of concept focused on the 5–10% of unusual loads that actually challenge the team.

# **2\. What We Understood (Project Scope)**

* The system is for cargo lifting at the port, for an upcoming vessel.  
* Identification is done through a mobile handheld app (Android): staff take a photo of the cargo with the phone camera and receive results in the app. No fixed camera or special hardware setup is needed.  
* From that photo, the app should suggest three things: dimensions, material/type (for example, metal, food, frozen items), and estimated weight.  
* About 95% of cargo is standard. The AI is mainly needed for the 5–10% of irregular or unusual loads that are difficult for the lifting team.  
* Most cargo is palletised, often with uneven heights and shapes. Some items are non-palletised machinery that need specific lifting points.  
* The AI will only recommend. A human lifting supervisor must validate the data and authorise the lift, for safety and legal responsibility.

# **3\. Feasibility — The Technology Stack**

| Component | Proposed | Suitable? | Note |
| :---- | :---- | :---- | :---- |
| Backend API | FastAPI | Yes | Fast, modern, and works naturally with Python AI libraries. |
| Language | Python 3.12 | Yes | The standard language for AI and computer-vision work. |
| Database | PostgreSQL | Yes | Reliable for storing cargo records, results, and history. |
| ORM | SQLAlchemy | Yes | Standard, works well with FastAPI and PostgreSQL. |
| Frontend | React | Yes | React for any web dashboard; React Native for the Android mobile app (same React family). |

Important point: The AI and image-analysis work also runs in Python, so it fits into the same stack. The stack is not a limitation. The limitations described next come from what a camera can physically measure — not from the technology you selected. (The specific AI tools and models are listed under Assumptions.)

# **4\. What a Camera Can and Cannot Do (The Core Reality)**

## **4.1 Material / Type — Reliable**

AI can identify material from the way a surface looks — metal is shiny, wood shows grain, cardboard has its own texture. This works well.

The limit: a camera can only see the outside. For example, a sealed carton of normal food and a sealed carton of frozen food can look the same. "Frozen" is a temperature, and a normal camera cannot see temperature.

Solution: take this detail from the shipping document/manifest, since it cannot be seen from the outside and printed labels on real cargo are often unreadable in field photos.

## **4.2 Dimensions (Size) — Possible, with a reference**

A single photo turns the real 3D world into a flat 2D image, so depth information is lost. Because of this, the camera does not know how far away an object is, and therefore cannot give an exact size on its own.

Simple example: in a photo, a large box placed far away can look the same size as a small box placed close. The camera cannot tell the difference by itself.

How we handle it (no extra hardware):

* Use a size reference already in the picture. Most cargo sits on standard-size pallets, and a pallet acts as a built-in ruler — so an ordinary phone photo is enough for a useful estimate.  
* Depth-estimation software (which runs on a normal phone photo) can further improve the estimate. If a phone already has a built-in depth sensor, it can be used when available — but this is optional, not required.

## **4.3 Weight — Estimate only, as a range**

Weight depends on two things: size and density (how heavy the material is for its size). We can estimate size from the image, but a camera cannot see density.

Simple example: two identical boxes — one full of cotton, one full of steel — look exactly the same in a photo, but their weights are completely different.

This is a law of physics, not a software weakness. No AI can read density from a picture.

What we do instead: once we know the material and the size, we estimate weight as a range (for example, "about 800–1100 kg") using typical density values for that material. The exact weight, where available, should come from the shipping documents/manifest. The AI's most valuable job here is cross-checking: if the document says 5000 kg but the AI estimate is around 1000 kg, the app raises a warning for the supervisor to check.

# **5\. Proposed Technical Approach**

## **5.1 How the system works — step by step**

* Capture — field staff take a photo of the cargo using the mobile app (phone camera).  
* Detect — the AI finds and separates the cargo item in the image.  
* Measure size — using the pallet (or another reference) in the photo, the system estimates dimensions.  
* Identify material — the AI classifies the material/type and reads any visible label text.  
* Estimate weight — using material \+ size, the system gives a weight range.  
* Cross-check — results are compared with the shipping document, if provided.  
* Show & validate — the app screen shows all results with a confidence level. The supervisor reviews, adjusts if needed, and approves.  
* Record — the approved data is stored for history and audit.

## **5.2 The AI / image-analysis part**

* Object detection and segmentation — locate the cargo and separate it from the background.  
* Dimension estimation — using a reference object (pallet) in the photo, aided by depth-estimation software.  
* Material classification — trained to recognise the cargo types the port handles.  
* Weight estimation — using a material-to-density reference table, always shown as a range with a confidence level.

## **5.3 Human-in-the-loop**

The system is an assistant. Every result is a recommendation with a clear confidence level. The supervisor always makes the final decision and authorises the lift. This keeps responsibility with a qualified person, as required.

## **5.4 Phased delivery**

| Phase | Purpose |
| :---- | :---- |
| Phase 1 — Proof of Concept | Test accuracy on a small set of real cargo, focused on the difficult 5–10% loads. Prove the approach before large investment. |
| Phase 2 — Pilot | A working app used alongside the current process for one vessel/section, to refine accuracy with real feedback. |
| Phase 3 — Production | Full system, integrated into the port workflow, with reporting and history. |

# **6\. Limitations and Recommended Alternatives**

| Limitation | Why it happens | Recommended alternative |
| :---- | :---- | :---- |
| Exact weight cannot come from a photo | A camera cannot see density | Use manifest weight where available; AI gives an estimated range and cross-checks it |
| Exact dimensions cannot come from a single photo | Depth is lost in a flat image | Use the standard pallet as a size reference in the photo, plus depth-estimation software; human validation covers the rest |
| Hidden properties (e.g. frozen vs normal) not visible | Camera sees only the outside | Take the value from the manifest/shipping document |
| Machinery lifting points are complex | Every machine is different | Start with detection support \+ supervisor judgment; improve with more data over time |
| Accuracy depends on training data | AI learns from examples | Collect and label real port cargo images during the PoC |

# **7\. Assumptions**

Because some details are not yet available, we have assumed the following. These directly affect accuracy, timeline, and cost, and we will confirm them during discovery. Everything AI-related below is an assumption, not a fixed commitment — the exact tools and models are selected during the PoC, based on the accuracy target and the available data.

## **7.1 Solution delivery**

* Identification is via a mobile handheld app (Android) using the phone camera. No fixed camera, camera rig, lighting setup, or special scanning hardware is required.  
* Because photos are handheld, lighting, angle and distance will vary. This is expected, and is exactly why we rely on a pallet size-reference, confidence scores, and human validation.  
* Network/data connectivity is assumed to be available all the time where photos are taken. An offline / queue-and-sync mode can be added in future if required.  
* Target platforms are assumed to be Android via one Flutter codebase (native builds are an option if preferred).

## **7.2 AI tools & technologies (assumed — mostly open-source, no per-use fee)**

| Purpose | Assumed tool/model | Why we use it (benefit) |
| :---- | :---- | :---- |
| AI framework | PyTorch or TensorFlow | The engine every AI model is built and run on. |
| Object detection & segmentation | YOLO, Segment Anything (SAM), or similar | Finds and cuts out the cargo in the photo — the first step before any measurement or classification. |
| Depth estimation (from a normal photo) | MiDaS / Depth Anything — software, no hardware | A flat photo loses depth, so size cannot be judged from it directly. This software estimates distance / 3D from an ordinary phone photo, which improves the size estimate — with no depth-camera hardware needed. |
| Material/type classification | Custom-trained image-classification model (CNN) | Recognises what the cargo is (metal, wood, food, etc.) from how the surface looks. Needed to pick the right density for the weight estimate and to flag the handling type. |
| Image processing & measurement | OpenCV | Prepares the photo and does the geometry — e.g. converting pixels to real size using the pallet as a reference. |
| Weight estimation | Material-to-density table \+ volume estimate (range output) | A camera cannot see weight. Once material \+ size are known, this estimates a weight range (volume × typical density) with a confidence level. The exact weight still comes from the manifest. |
| Data labelling (build phase only) | Roboflow or CVAT | Used only during development to label training images so the models can learn. |
| Model training compute | GPU (cloud or local) | Needed to train and run the models quickly during development. |
| Optional (only if needed) | Cloud vision / multimodal AI APIs | Faster to start, but carry a per-use cost and send data to a third party. |

* Open-source first: the tools above are mostly free/open-source, so there is no per-use AI fee. Cloud AI APIs are optional and only used if they clearly improve accuracy or speed.  
* No special hardware: the depth camera / LiDAR / 3D scanner raised in early discussions is not required for the mobile-app approach. Depth is handled in software; a phone's own sensor is used only if it happens to have one.  
* On-device vs server: AI processing is assumed to run on the server (backend), with the app sending the photo and showing the result. On-device processing can be explored later if needed.

## **7.3 Data, accuracy & volume**

* Dataset: sample cargo images and a few shipping documents can be provided, or collected during the PoC. If no data is available, extra time is needed to collect and label it.  
* Expected accuracy: material/type and size (with a pallet reference) can reach a useful accuracy; weight is delivered as a range, not an exact figure. A specific target is agreed at the PoC.  
* Transaction volume: a moderate number of cargo checks per day is assumed. Final numbers (photos per day, peak load) are needed to size the servers.

## **7.4 Process & integration**

* Manifest/document access is available for cross-checking where applicable.  
* Integration with any existing port system is to be confirmed once its API is known.  
* The AI is recommendation-only; a human supervisor validates and authorises every lift.

## **7.5 Optional: Third-Party AI API (GPT / Claude / Gemini Vision)**

Instead of training our own models, the image analysis can also be done through a

ready-made multimodal AI API (OpenAI GPT, Anthropic Claude, or Google Gemini).

* Helps: no dataset needed to start for PoC, good at material/type and  
  reading clear labels, and handles unusual cargo well.  
* Trade-offs: recurring per-use cost, cargo photos go to a third-party server  
  (data-privacy approval needed), needs internet, and it still cannot measure exact  
  size or weight.

## **7.6 Training Data — How Many Images Are Needed**

To reach a useful PoC-level accuracy (\~50–60%), we assume roughly

500 – 800 good, varied images per cargo category — about 1500–2,500 images total

(depending on the number of categories), with \~15–20% kept aside only for testing.

Why this many:

* The AI learns from examples; with too few, it memorises instead of learning and fails  
  on new photos.  
* Real conditions vary (day/night, angle, distance, wrapping, cluttered background),  
  so each condition needs examples.  
* Each cargo type needs enough of its own examples (class balance).  
* Using pre-trained models (transfer learning), we only fine-tune — so a few hundred per  
  category are enough, not millions.  
* Accuracy rises with more data but with diminishing returns (≈100/category → \~55–60%,  
  ≈500 → \~72%, 1,000+ → \~80%).

Variety matters more than raw count: 200 varied images beat 1,000 near-identical ones.

The exact number is confirmed at the PoC, based on the number of categories and image quality.

# **8\. Indicative Timeline**

The timeline below is indicative and will be confirmed after a short discovery phase and final scope.

This is the sheet for the timeline:

 [AI-Cargo-Project-Timeline](https://docs.google.com/spreadsheets/d/1cFk0qRtuzduAzVEXRNuuwc5FzKoXi0fjxX9oodNa39M/edit?usp=sharing)

# **9\. Ongoing / Recurring Cost Considerations**

* Hosting/servers (and GPU, if used for processing).  
* AI API usage — only if cloud vision / multimodal APIs are chosen (per-use cost).  
* Mobile app store accounts — Apple Developer and Google Play developer fees (annual/one-time).  
* Data storage for images and records.  
* Model maintenance/retraining as new cargo types appear.  
* Software support and updates (including OS/app updates for Android).

Using open-source AI models (as recommended) keeps recurring AI costs low, because there is no per-use fee for them.

