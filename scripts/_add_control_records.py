"""One-off: write the hand-written control records for the non-shoulder regions.

These are the NON-CIRCULAR control (CLAUDE.md rule 21b). Two properties matter and neither is
automatic:

  1. The prose is written by HAND, deliberately using phrasings the generator never produces —
     "we spent about twenty-five minutes on", "I did fifteen minutes of manual", "held off on",
     "once she's cleared". The generator can only ever speak the frames in `evals/synth/banks.py`,
     so a corpus built from it cannot surface a gap in those frames. This set can.
  2. The billing gold is labeled by READING each transcript, never by running the extractor and
     accepting its output, which would make every accuracy number circular.

`gold_provenance.verified_by` is left BLANK: hand-read is not clinician-verified, and the sign-off
gate in tests/test_billing_extract.py keeps saying so until a clinician fills it in.

Run once:  .venv/Scripts/python.exe scripts/_add_control_records.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.generate.billing import AMA_RULE_OF_EIGHTS, allocate_units, units_for_minutes
from app.generate.cpt import is_timed

L = "Therapeutic Exercise"; M = "Manual Therapy"; N = "Neuromuscular Re-education"
A = "Therapeutic Activities"; G = "Gait Training"; E = "Electrical Stimulation"
H = "Hot/Cold Packs"; T = "Mechanical Traction"; U = "Ultrasound"

RECORDS = [
    # ---------------------------------------------------------------- knee
    dict(
        id=201, part="knee", name="Delphine Marchetti-Osei",
        dx="S/P right total knee arthroplasty", visit="Follow-up, post-op week 4",
        date="2026-04-06",
        transcript=(
            "Okay, follow up for Delphine, right knee, she's four weeks out from a right total "
            "knee replacement. Reports the swelling is down and she's finally sleeping through "
            "the night. Pain three out of ten at rest, six out of ten on stairs. Range of motion "
            "today, right knee flexion one hundred five degrees, extension lacking five degrees. "
            "We spent about twenty-five minutes on ther ex, quad sets, heel slides, and short arc "
            "quads. Then I did fifteen minutes of manual therapy, patellar mobilizations and scar "
            "work along the incision. Finished with ten minutes of gait training in the hallway "
            "with the rolling walker, cueing for heel strike. Held off on the e-stim today "
            "because the swelling was already down. Once she's cleared by the surgeon we'll start "
            "neuromuscular re-education for quad control. She's doing the heel slides and quad "
            "sets at home twice a day. Total treatment time fifty minutes. Tolerated everything "
            "well, no increase in effusion."
        ),
        icd=[("Z47.1", "Aftercare following joint replacement surgery")],
        iv=[("97110", L, 25), ("97140", M, 15), ("97116", G, 10)],
        dis=[("97014", "negated"), ("97112", "planned")],
        note="'four weeks out from' is a post-surgical framing the ICD context cues do not "
             "recognize — a deliberate recall probe. 50 timed min: CMS 3 units vs AMA 4.",
    ),
    dict(
        id=202, part="knee", name="Ignatius Vandermeer",
        dx="Right patellofemoral pain syndrome", visit="Follow-up, week 5",
        date="2026-04-13",
        transcript=(
            "Follow up, Ignatius, right knee. The referral says right patellofemoral pain "
            "syndrome. He's a recreational runner, says the pain going downhill is the worst of "
            "it. Two out of ten at rest, five out of ten with descending stairs. Today, twenty "
            "minutes of therapeutic exercise, straight leg raises, wall sits, and hip abductor "
            "work with the band. Then twelve minutes of neuromuscular re-education, single leg "
            "balance and step-down control with mirror feedback for the valgus collapse. Last "
            "visit we did cold packs afterward but he didn't need it today. Next visit we plan to "
            "start therapeutic activities with a return to running progression. Quad strength "
            "right four minus out of five, left five out of five."
        ),
        icd=[("M22.2X1", "Patellofemoral disorders, right knee")],
        iv=[("97110", L, 20), ("97112", N, 12)],
        dis=[("97010", "prior_visit"), ("97530", "planned")],
        note="'The referral says X' is a diagnosis framing the generator never produces.",
    ),
    # -------------------------------------------------------------- lumbar
    dict(
        id=301, part="lumbar", name="Bartholomew Nkemelu",
        dx="Lumbago with sciatica, right side", visit="Follow-up, week 3",
        date="2026-04-20",
        transcript=(
            "Alright, follow up for Bartholomew, low back. He comes in with a diagnosis of "
            "lumbago with sciatica on the right. He says the leg pain is no longer going past the "
            "knee, which is a good sign, centralizing. Pain four out of ten in the back, two out "
            "of ten in the leg. Today I did twenty minutes of manual therapy, central "
            "posteroanterior mobilizations at L4 and L5 and soft tissue work to the right "
            "paraspinals and QL. Then eighteen minutes of ther ex, prone press ups, transverse "
            "abdominis activation, and bridging. Then fifteen minutes of therapeutic activities, "
            "floor to waist lifting mechanics with a ten pound crate. Previously we were using "
            "mechanical traction but we've moved away from that. No electrical stimulation today. "
            "Straight leg raise on the right is now sixty degrees, up from forty-five."
        ),
        icd=[("M54.41", "Lumbago with sciatica, right side")],
        iv=[("97140", M, 20), ("97110", L, 18), ("97530", A, 15)],
        dis=[("97012", "prior_visit"), ("97014", "negated")],
        note="53 timed min: CMS 4 units vs AMA 3 — divergence in the control set.",
    ),
    dict(
        id=302, part="lumbar", name="Cressida Aumonier",
        dx="Lumbar disc herniation", visit="Follow-up, week 2",
        date="2026-04-27",
        transcript=(
            "Follow up, Cressida, low back. Working diagnosis is a lumbar herniated disc at L5 "
            "S1. She reports she can sit through a full meeting now, about forty minutes, up from "
            "fifteen. Pain three out of ten. Today we did twenty-two minutes of therapeutic "
            "exercise, McKenzie extension progression and hip hinge patterning. Then fifteen "
            "minutes of neuromuscular re-education working on neutral spine control during "
            "lifting. Next time we plan to start manual therapy now that the acute irritability "
            "has settled. She's doing the press ups at home every two hours."
        ),
        icd=[("M51.26", "Other intervertebral disc displacement, lumbar region")],
        iv=[("97110", L, 22), ("97112", N, 15)],
        dis=[("97140", "planned")],
        note="Non-lateralized lumbar code: no 'confirm right or left' gap should be raised.",
    ),
    # ------------------------------------------------------------ cervical
    dict(
        id=401, part="cervical", name="Perpetua Lindqvist-Barrow",
        dx="Cervical sprain following motor vehicle collision", visit="Follow-up, week 4",
        date="2026-05-04",
        transcript=(
            "Follow up for Perpetua, neck. Medical diagnosis is a cervical sprain following a "
            "rear end collision six weeks ago. She reports the headaches are down to about two a "
            "week from daily. Cervical rotation is seventy degrees to the right and sixty to the "
            "left, up from fifty bilaterally. Today, eighteen minutes of manual therapy, "
            "unilateral posteroanterior mobilizations at C5 and C6 plus suboccipital release. "
            "Then fifteen minutes of therapeutic exercise, deep neck flexor endurance and "
            "scapular retraction. Then ten minutes of neuromuscular re-education for postural "
            "retraining with mirror feedback. She uses a hot pack at home before her exercises. "
            "Next visit we will add mechanical traction if the arm symptoms persist."
        ),
        icd=[("S13.4XX", "Sprain of ligaments of cervical spine")],
        iv=[("97140", M, 18), ("97110", L, 15), ("97112", N, 10)],
        dis=[("97010", "home_program"), ("97012", "planned")],
        note="Sprain code needs a 7th character — the caution must reach the clinician.",
    ),
    dict(
        id=402, part="cervical", name="Osgood Ferrantelli",
        dx="Cervicalgia", visit="Follow-up, week 6",
        date="2026-05-11",
        transcript=(
            "Follow up, Osgood, neck. Treating diagnosis is cervicalgia. Desk worker, says the "
            "pain builds through the afternoon. Four out of ten by end of day, one out of ten in "
            "the morning. Gave him twenty minutes of therapeutic exercise today, chin tucks, "
            "scapular setting, and upper trap stretching. Then twelve minutes of manual therapy "
            "to the upper trapezius and levator scapulae. We did not do electrical stimulation "
            "today, he said it hasn't been helping. Reviewed his workstation setup and monitor "
            "height."
        ),
        icd=[("M54.2", "Cervicalgia")],
        iv=[("97110", L, 20), ("97140", M, 12)],
        dis=[("97014", "negated")],
        note="'Gave him X minutes of' is a phrasing the generator never produces. M54.2 is "
             "non-lateralized.",
    ),
    # ----------------------------------------------------------------- hip
    dict(
        id=501, part="hip", name="Anastasia Wrottesley",
        dx="S/P left total hip arthroplasty", visit="Follow-up, post-op week 6",
        date="2026-05-18",
        transcript=(
            "This is Anastasia, six weeks post left total hip replacement, posterior approach. "
            "She's off the walker and using a single point cane in the house. Pain two out of "
            "ten. Today twenty minutes of ther ex, clamshells, side lying abduction, and standing "
            "hip extension. Then fifteen minutes of gait training with the cane, working on step "
            "length symmetry and reducing the Trendelenburg. Then twelve minutes of therapeutic "
            "activities, sit to stand from a low surface and car transfer training. We are not "
            "doing manual therapy at the hip given the posterior precautions. Once she's twelve "
            "weeks out we'll begin neuromuscular re-education for single leg stance. Hip abductor "
            "strength left three plus out of five."
        ),
        icd=[("Z47.1", "Aftercare following joint replacement surgery")],
        iv=[("97110", L, 20), ("97116", G, 15), ("97530", A, 12)],
        dis=[("97140", "negated"), ("97112", "planned")],
        note="'six weeks post X' should reach the ICD table via the 'weeks post' context cue. "
             "'We are not doing X' is a negation form the generator never produces.",
    ),
    dict(
        id=502, part="hip", name="Thaddeus Okonjo-Bright",
        dx="Right greater trochanteric pain syndrome", visit="Follow-up, week 4",
        date="2026-05-25",
        transcript=(
            "Follow up, Thaddeus, right hip. Referring diagnosis is right greater trochanteric "
            "pain syndrome. He says lying on that side at night is still the problem but walking "
            "is much better. Today, twenty-five minutes of therapeutic exercise, isometric hip "
            "abduction, side plank progression, and single leg bridging. Then fifteen minutes of "
            "manual therapy, soft tissue work to the gluteus medius and tensor fasciae latae. Last "
            "visit we tried ultrasound over the trochanter but he didn't notice a difference so we "
            "skipped it. Educated on sleeping with a pillow between the knees."
        ),
        icd=[("M70.61", "Trochanteric bursitis, right hip")],
        iv=[("97110", L, 25), ("97140", M, 15)],
        dis=[("97035", "prior_visit")],
        note="40 timed min: CMS 3 units vs AMA 3. 'greater trochanteric pain syndrome' must map "
             "to the trochanteric bursitis rule.",
    ),
    # --------------------------------------------------------------- ankle
    dict(
        id=601, part="ankle", name="Marguerite Szymanski-Oyelaran",
        dx="Right lateral ankle sprain, grade II", visit="Follow-up, week 3",
        date="2026-06-01",
        transcript=(
            "Follow up for Marguerite, right ankle. She was referred with a diagnosis of a right "
            "lateral ankle sprain, grade two, rolled it playing netball three weeks ago. Swelling "
            "is nearly resolved, she's full weight bearing without the boot. Dorsiflexion is ten "
            "degrees on the right, fifteen on the left. Today, eighteen minutes of ther ex, ankle "
            "four way with the band, heel raises, and towel scrunches. Then twenty minutes of "
            "neuromuscular re-education, single leg balance on the wobble board and on foam with "
            "eyes closed. Then ten minutes of manual therapy, talocrural anterior posterior "
            "glides. She's using an ice pack at home after work. We'll begin gait training on "
            "uneven surfaces at the next session."
        ),
        icd=[("S93.421", "Sprain of calcaneofibular ligament of right ankle")],
        iv=[("97110", L, 18), ("97112", N, 20), ("97140", M, 10)],
        dis=[("97010", "home_program"), ("97116", "planned")],
        note="48 timed min: CMS 3 units vs AMA 3.",
    ),
    dict(
        id=602, part="ankle", name="Fitzwilliam Adeyemi-Stroud",
        dx="Plantar fasciitis", visit="Follow-up, week 8",
        date="2026-06-08",
        transcript=(
            "Follow up, Fitzwilliam, left foot. Diagnosis is plantar fasciitis. He says the first "
            "steps in the morning are much better, maybe a two out of ten now versus a seven when "
            "we started. Still sore after standing all day at work. Twenty minutes of therapeutic "
            "exercise today, eccentric heel drops off the step, calf stretching, and intrinsic "
            "foot strengthening with the towel. Then fifteen minutes of manual therapy, soft "
            "tissue work to the plantar fascia and the gastrocsoleus complex. Previously we were "
            "doing ultrasound to the heel. He's continuing the night splint."
        ),
        icd=[("M72.2", "Plantar fascial fibromatosis")],
        iv=[("97110", L, 20), ("97140", M, 15)],
        dis=[("97035", "prior_visit")],
        note="M72.2 is NOT lateralized — no laterality gap should be raised even though 'left "
             "foot' is stated.",
    ),
]


def main() -> int:
    out_dir = Path(__file__).resolve().parent.parent / "evals" / "data"
    by_part: dict[str, list[dict]] = {}
    for spec in RECORDS:
        ivs = [{"code": c, "label": lab, "minutes": m, "timed": is_timed(c), "billable": True}
               for c, lab, m in spec["iv"]]
        timed_total = sum(i["minutes"] for i in ivs if i["timed"] and i["minutes"])
        per_code = {i["code"]: i["minutes"] for i in ivs if i["timed"] and i["minutes"]}
        rec = {
            "id": spec["id"],
            "patient_name": spec["name"],
            "diagnosis": spec["dx"],
            "visit_type": spec["visit"],
            "date": spec["date"],
            "transcript": spec["transcript"],
            "cpt_codes": [{"code": i["code"], "description": i["label"]} for i in ivs],
            "body_part": spec["part"],
            "icd_codes": [{"code": c, "description": d} for c, d in spec["icd"]],
            "interventions": ivs,
            "distractors": [{"code": c, "reason": r} for c, r in spec["dis"]],
            "total_timed_minutes": timed_total,
            "expected_units": units_for_minutes(timed_total),
            "expected_units_ama": allocate_units(per_code, method=AMA_RULE_OF_EIGHTS).total_units,
            "synth": {},   # empty == hand-written; this is what `is_synthetic` keys on
            "gold_provenance": {
                "labeled_by": "hand-read from the transcript (NOT the extractor)",
                "verified_by": "", "verified_on": "",
                "note": spec["note"],
            },
        }
        by_part.setdefault(spec["part"], []).append(rec)
        cms, ama = rec["expected_units"], rec["expected_units_ama"]
        print(f"  {rec['id']} {spec['part']:<9} {[c for c, _ in spec['icd']]} "
              f"{[i['code'] for i in ivs]} {timed_total}min -> {cms}u CMS"
              + (f" / {ama}u AMA  <-- DIVERGENT" if cms != ama else f" / {ama}u AMA"))

    for part, recs in by_part.items():
        path = out_dir / f"{part}_control.jsonl"
        path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in recs) + "\n",
                        encoding="utf-8")
        print(f"wrote {len(recs)} -> {path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
