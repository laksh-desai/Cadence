/*
 * Exercise library.
 *
 * Each exercise:
 *   id        unique, never change once programs have been shared (links refer to it)
 *   name, region ('neck' | 'back' | 'shoulder' | 'hand' | 'leg'), area (finer label)
 *   type      'stretch' | 'strength' | 'mobility' | 'balance'
 *   position, equipment[]
 *   summary   one line
 *   steps[]   plain-language instructions
 *   tips[]    optional coaching cues
 *   caution   when to stop / take care
 *   dose      { sets, reps, hold (seconds), perDay, sides (true = each side) }
 *   fig       illustration (see js/figures.js) or null for instructions only
 *
 * Content is general guidance written for a therapist to review and adjust.
 */
(function (global) {
  'use strict';
  var F = global.HEPFig, p = F.pose;

  var CHAIR = [{ t: 'chair' }];

  var EX = [
    /* ================= NECK ================= */
    {
      id: 'neck-chin-tuck', name: 'Chin tucks', region: 'neck', area: 'Neck posture', type: 'strength',
      position: 'Sitting', equipment: ['Chair'],
      summary: 'Draw the chin straight back to strengthen deep neck muscles and improve posture.',
      steps: [
        'Sit tall with your shoulders relaxed and eyes looking straight ahead.',
        'Gently glide your chin straight back, as if making a "double chin".',
        'Keep your eyes level. Do not tip your head up or down.',
        'Hold, then slowly relax forward again.'
      ],
      tips: ['Imagine a string pulling the top of your head toward the ceiling.', 'At the end, your ears should be right above your shoulders.'],
      caution: 'Move gently. Stop if you feel dizziness, tingling or pain spreading down the arm.',
      dose: { sets: 1, reps: 10, hold: 5, perDay: 3 },
      fig: { view: 'side', focus: ['neck'],
        props: [{ t: 'chair' }, { t: 'arrow', at: 'head', dx: 27, dy: -1, angle: 270, len: 9 }],
        poses: [
          // start: head poking forward of the shoulders, chin slightly up
          p('sitSide', { neck: 154, face: 99 }),
          // end: head glided straight back over the shoulders, chin slightly down, eyes level
          p('sitSide', { neck: 181, face: 82 })
      ] }
    },
    {
      id: 'neck-side-bend', name: 'Neck side-bend stretch', region: 'neck', area: 'Upper trapezius', type: 'stretch',
      position: 'Sitting', equipment: ['Chair'],
      summary: 'Tilt the ear toward the shoulder to stretch the side of the neck.',
      steps: [
        'Sit tall and hold the edge of the chair with one hand.',
        'Slowly tilt your head, bringing your ear toward the opposite shoulder.',
        'Keep looking forward and keep both shoulders down.',
        'Hold where you feel a gentle stretch, then return to the middle. Repeat on the other side.'
      ],
      tips: ['For a little more stretch, rest your free hand lightly on the side of your head. Do not pull.'],
      caution: 'A stretch should feel mild. Stop if you feel sharp pain, numbness or tingling.',
      dose: { sets: 1, reps: 3, hold: 30, perDay: 2, sides: true },
      fig: { view: 'front', props: CHAIR, focus: ['neck'], poses: [
        p('sitFront', {}),
        p('sitFront', { neck: 150 })
      ] }
    },
    {
      id: 'neck-rotation', name: 'Neck rotation', region: 'neck', area: 'Neck mobility', type: 'mobility',
      position: 'Sitting', equipment: ['Chair'],
      summary: 'Turn the head side to side to keep the neck moving.',
      steps: [
        'Sit tall with your shoulders relaxed.',
        'Slowly turn your head to look over one shoulder as far as is comfortable.',
        'Return to the middle, then turn to the other side.',
        'Keep your chin level throughout.'
      ],
      caution: 'Move slowly. Stop if you feel dizzy or lightheaded.',
      dose: { sets: 1, reps: 10, hold: 2, perDay: 3, sides: true },
      fig: { view: 'front', props: CHAIR, focus: ['neck'], poses: [
        p('sitFront', { turn: -1 }),
        p('sitFront', { turn: 1 })
      ] }
    },
    {
      id: 'neck-flexion', name: 'Chin-to-chest stretch', region: 'neck', area: 'Back of neck', type: 'stretch',
      position: 'Sitting', equipment: ['Chair'],
      summary: 'Lower the chin toward the chest to stretch the back of the neck.',
      steps: [
        'Sit tall with your shoulders relaxed.',
        'Slowly lower your chin toward your chest.',
        'Hold where you feel a gentle stretch at the back of the neck.',
        'Slowly lift your head back to upright.'
      ],
      caution: 'Stop if you feel tingling or pain going into the arms.',
      dose: { sets: 1, reps: 3, hold: 20, perDay: 2 },
      fig: { view: 'side', props: CHAIR, focus: ['neck'], poses: [
        p('sitSide', {}),
        p('sitSide', { neck: 150, face: 25 })
      ] }
    },
    {
      id: 'neck-extension', name: 'Gentle look-up', region: 'neck', area: 'Neck mobility', type: 'mobility',
      position: 'Sitting', equipment: ['Chair'],
      summary: 'Slowly look up toward the ceiling and back to restore neck movement.',
      steps: [
        'Sit tall and do a small chin tuck first.',
        'Slowly look up toward the ceiling, only as far as is comfortable.',
        'Return to looking straight ahead.'
      ],
      caution: 'Skip this exercise and tell your therapist if looking up makes you dizzy, or if you have blurred vision or nausea.',
      dose: { sets: 1, reps: 10, hold: 2, perDay: 2 },
      fig: { view: 'side', props: CHAIR, focus: ['neck'], poses: [
        p('sitSide', {}),
        p('sitSide', { neck: 196, face: 145 })
      ] }
    },
    {
      id: 'neck-levator-stretch', name: 'Levator scapulae stretch', region: 'neck', area: 'Neck & top of shoulder', type: 'stretch',
      position: 'Sitting', equipment: ['Chair'],
      summary: 'Turn the nose toward the armpit and look down to stretch the back of the neck and top of the shoulder.',
      steps: [
        'Sit tall and hold the chair seat with one hand to keep that shoulder down.',
        'Turn your head about halfway toward the other side.',
        'Bend your head down, as if looking into your opposite armpit.',
        'Hold the gentle stretch, then slowly return. Repeat on the other side.'
      ],
      caution: 'A mild stretch only. Stop if you feel tingling or pain going down the arm.',
      dose: { sets: 1, reps: 3, hold: 30, perDay: 2, sides: true },
      fig: { view: 'front', props: CHAIR, focus: ['neck'], poses: [
        p('sitFront', {}),
        p('sitFront', { neck: 160, turn: 0.75, armL: [-4, -2] })
      ] }
    },
    {
      id: 'neck-isometric-side', name: 'Neck isometric (side press)', region: 'neck', area: 'Neck strength', type: 'strength',
      position: 'Sitting', equipment: ['Chair'],
      summary: 'Press the head gently into the hand without moving, to build neck strength.',
      steps: [
        'Sit tall and place your palm on the side of your head, above your ear.',
        'Gently push your head into your hand, using about a quarter of your effort.',
        'Resist with your hand so your head does not move.',
        'Hold, then relax. Repeat on the other side.'
      ],
      tips: ['Keep breathing normally while you press.'],
      caution: 'Use gentle effort only. It should not cause pain.',
      dose: { sets: 1, reps: 5, hold: 5, perDay: 2, sides: true },
      fig: { view: 'front', props: CHAIR, focus: ['neck', 'armR'], poses: [
        p('sitFront', { armR: [120, -97] }),
        p('sitFront', { armR: [120, -99], neck: 177 })
      ] }
    },

    /* ================= BACK ================= */
    {
      id: 'back-pelvic-tilt', name: 'Pelvic tilts', region: 'back', area: 'Lower back', type: 'mobility',
      position: 'Lying on back', equipment: ['Mat or bed'],
      summary: 'Gently flatten and arch the lower back to ease stiffness.',
      steps: [
        'Lie on your back with your knees bent and feet flat.',
        'Tighten your stomach muscles and gently press your lower back into the floor.',
        'Hold, then relax and let your back return to its natural curve.',
        'Keep your buttocks on the floor throughout.'
      ],
      caution: 'Keep the movement small and comfortable.',
      dose: { sets: 1, reps: 10, hold: 5, perDay: 2 },
      fig: { view: 'side', focus: ['torso'], poses: [
        p('hook', { arch: 2.5 }),
        p('hook', { arch: -1.5 })
      ] }
    },
    {
      id: 'back-knee-to-chest', name: 'Single knee to chest', region: 'back', area: 'Lower back & buttock', type: 'stretch',
      position: 'Lying on back', equipment: ['Mat or bed'],
      summary: 'Hug one knee toward the chest to stretch the lower back.',
      steps: [
        'Lie on your back with both knees bent.',
        'Bring one knee toward your chest and hold it with both hands behind the thigh.',
        'Gently pull until you feel a stretch in your lower back or buttock.',
        'Hold, then lower the leg slowly. Repeat with the other leg.'
      ],
      caution: 'Stop if this increases pain down the leg.',
      dose: { sets: 1, reps: 3, hold: 20, perDay: 2, sides: true },
      fig: { view: 'side', focus: ['legR'], poses: [
        p('hook', {}),
        p('hook', { legR: [200, 95, 150], armR: [150, 121], armL: [150, 121] })
      ] }
    },
    {
      id: 'back-trunk-rotation', name: 'Lower trunk rotation', region: 'back', area: 'Lower back', type: 'mobility',
      position: 'Lying on back', equipment: ['Mat or bed'],
      summary: 'Let the bent knees roll gently side to side.',
      steps: [
        'Lie on your back with your knees bent, feet flat and knees together.',
        'Stretch your arms out to the sides.',
        'Slowly let both knees roll to one side as far as is comfortable, keeping your shoulders down.',
        'Bring the knees back to the middle and roll to the other side.'
      ],
      tips: ['This drawing shows you from above.'],
      caution: 'Keep within a comfortable range.',
      dose: { sets: 1, reps: 10, hold: 3, perDay: 2, sides: true },
      fig: { view: 'front', floor: false, focus: ['legR', 'legL'], poses: [
        p('standFront', { torso: 270, neck: 270, armR: [180, 180], armL: [0, 0], legR: [80, 100, 100, 0.45, 0.15], legL: [100, 80, 80, 0.45, 0.15] }),
        p('standFront', { torso: 270, neck: 270, armR: [180, 180], armL: [0, 0], legR: [30.6, 153.4, 153.4, 0.92, 0.81], legL: [35, 148.7, 148.7, 0.72, 0.82] })
      ] }
    },
    {
      id: 'back-cat-camel', name: 'Cat-camel', region: 'back', area: 'Whole spine', type: 'mobility',
      position: 'Hands and knees', equipment: ['Mat'],
      summary: 'Round and gently arch the back on hands and knees.',
      steps: [
        'Kneel on all fours with your hands under your shoulders and knees under your hips.',
        'Slowly round your back up toward the ceiling, letting your head drop.',
        'Then let your back gently sag and lift your head to look forward.',
        'Move slowly and smoothly between the two positions.'
      ],
      caution: 'Use a cushion under the knees if needed. Keep the movement comfortable.',
      dose: { sets: 1, reps: 10, hold: 3, perDay: 2 },
      fig: { view: 'side', focus: ['torso'], poses: [
        p('quad', { arch: -9, neck: 40 }),
        p('quad', { arch: 6, neck: 125 })
      ] }
    },
    {
      id: 'back-prone-press-up', name: 'Prone press-up', region: 'back', area: 'Lower back', type: 'mobility',
      position: 'Lying on stomach', equipment: ['Mat or bed'],
      summary: 'Push the upper body up while the hips stay down, to extend the lower back.',
      steps: [
        'Lie on your stomach with your hands flat on the floor near your shoulders.',
        'Slowly straighten your arms to lift your chest, keeping your hips on the floor.',
        'Let your lower back relax and sag.',
        'Hold briefly, then lower yourself slowly.'
      ],
      tips: ['Start by propping up on your elbows if straightening your arms is too much.'],
      caution: 'Stop and tell your therapist if pain spreads further down the leg.',
      dose: { sets: 1, reps: 10, hold: 2, perDay: 3 },
      fig: { view: 'side', focus: ['torso'], poses: [
        p('prone', {}),
        p('prone', { torso: 145, neck: 150, armR: [41.6, 41.6], armL: [41.6, 41.6] })
      ] }
    },
    {
      id: 'back-bridge', name: 'Bridge', region: 'back', area: 'Buttocks & lower back', type: 'strength',
      position: 'Lying on back', equipment: ['Mat or bed'],
      summary: 'Lift the hips from lying to strengthen the buttocks and back.',
      steps: [
        'Lie on your back with your knees bent and feet flat, hip-width apart.',
        'Tighten your stomach and squeeze your buttocks.',
        'Lift your hips until your body is in a straight line from shoulders to knees.',
        'Hold, then lower slowly.'
      ],
      tips: ['Push through your heels. Do not arch your back.'],
      caution: 'Stop if you feel pain in the lower back. Try a smaller lift.',
      dose: { sets: 2, reps: 10, hold: 3, perDay: 1 },
      fig: { view: 'side', focus: ['torso', 'thighR'], poses: [
        p('hook', {}),
        p('hook', { torso: 300, neck: 262, armR: [90, 90], armL: [90, 90], legR: [110, -1, 90], legL: [110, -1, 90] })
      ] }
    },
    {
      id: 'back-bird-dog', name: 'Bird-dog', region: 'back', area: 'Core & back', type: 'strength',
      position: 'Hands and knees', equipment: ['Mat'],
      summary: 'Reach out with the opposite arm and leg while keeping the back still.',
      steps: [
        'Kneel on all fours with your back flat.',
        'Tighten your stomach muscles.',
        'Slowly reach one arm forward and the opposite leg back, keeping your hips level.',
        'Hold, then return. Switch sides.'
      ],
      tips: ['Imagine balancing a cup of water on your lower back.', 'Start with just the arm, or just the leg, if needed.'],
      caution: 'Keep the back flat. Do not let it sag.',
      dose: { sets: 1, reps: 10, hold: 5, perDay: 1, sides: true },
      fig: { view: 'side', focus: ['armR', 'legL'], poses: [
        p('quad', {}),
        p('quad', { armR: [97, 97], legL: [263, 263, 263] })
      ] }
    },
    {
      id: 'back-childs-pose', name: "Child's pose stretch", region: 'back', area: 'Lower & mid back', type: 'stretch',
      position: 'Kneeling', equipment: ['Mat'],
      summary: 'Sit back toward the heels with arms reaching forward.',
      steps: [
        'Start on all fours.',
        'Slowly sit your buttocks back toward your heels.',
        'Let your chest lower toward your thighs and keep your arms reaching forward on the floor.',
        'Breathe slowly and hold, then return to all fours.'
      ],
      caution: 'Use a pillow under your knees or chest if needed. Skip this if it hurts your knees.',
      dose: { sets: 1, reps: 3, hold: 30, perDay: 2 },
      fig: { view: 'side', focus: ['torso'], poses: [
        p('quad', {}),
        p('quad', { torso: 70, neck: 95, legR: [50, 270, 270], legL: [50, 270, 270], armR: [75, 85], armL: [75, 85] })
      ] }
    },
    {
      id: 'back-standing-extension', name: 'Standing back bend', region: 'back', area: 'Lower back', type: 'mobility',
      position: 'Standing', equipment: [],
      summary: 'Lean back gently with hands on the hips to reverse prolonged sitting.',
      steps: [
        'Stand with your feet hip-width apart.',
        'Place your hands on your lower back or hips.',
        'Gently lean backward, using your hands for support.',
        'Hold briefly, then return to upright.'
      ],
      caution: 'Stop if this causes pain down the leg or makes you dizzy.',
      dose: { sets: 1, reps: 5, hold: 2, perDay: 3 },
      fig: { view: 'side', focus: ['torso'], poses: [
        p('standSide', { armR: [345, 40], armL: [345, 40] }),
        p('standSide', { torso: 200, neck: 205, face: 130, armR: [5, 60], armL: [5, 60], legR: [-6, -6, 90], legL: [-6, -6, 90] })
      ] }
    },

    /* ================= SHOULDER ================= */
    {
      id: 'sh-pendulum', name: 'Pendulum swings', region: 'shoulder', area: 'Shoulder mobility', type: 'mobility',
      position: 'Standing, leaning', equipment: ['Table or counter'],
      summary: 'Let the arm hang and swing gently to loosen the shoulder.',
      steps: [
        'Lean forward with your good hand resting on a table.',
        'Let your sore arm hang straight down and relax.',
        'Gently rock your body so the arm swings forward and back, then side to side, then in small circles.',
        'Let your body make the movement. Keep the arm relaxed.'
      ],
      caution: 'Keep the swings small and painless.',
      dose: { sets: 1, reps: 10, perDay: 3 },
      fig: { view: 'side', focus: ['armR'], props: [{ t: 'table', at: 'haL', w: 50, dx: 14 }], poses: [
        p('standSide', { torso: 118, neck: 115, armL: [55, 40], armR: [-14, -14], legR: [8, 0, 90], legL: [-8, 0, 90] }),
        p('standSide', { torso: 118, neck: 115, armL: [55, 40], armR: [14, 14], legR: [8, 0, 90], legL: [-8, 0, 90] })
      ] }
    },
    {
      id: 'sh-scap-squeeze', name: 'Shoulder blade squeeze', region: 'shoulder', area: 'Upper back & posture', type: 'strength',
      position: 'Sitting or standing', equipment: [],
      summary: 'Squeeze the shoulder blades together to improve posture.',
      steps: [
        'Sit or stand tall with your arms relaxed and elbows bent.',
        'Gently draw your shoulder blades back and down, as if putting them in your back pockets.',
        'Do not shrug your shoulders up.',
        'Hold, then relax.'
      ],
      dose: { sets: 1, reps: 10, hold: 5, perDay: 3 },
      fig: { view: 'side', props: CHAIR, focus: ['armR', 'torso'], poses: [
        p('sitSide', { armR: [8, 90], armL: [8, 90] }),
        p('sitSide', { armR: [-22, 90], armL: [-22, 90], neck: 183 })
      ] }
    },
    {
      id: 'sh-wall-walk', name: 'Wall finger walk', region: 'shoulder', area: 'Shoulder flexion', type: 'mobility',
      position: 'Standing, facing a wall', equipment: ['Wall'],
      summary: 'Walk the fingers up a wall to gradually raise the arm.',
      steps: [
        'Stand facing a wall, about an arm’s length away.',
        'Place your fingertips on the wall at chest height.',
        'Slowly walk your fingers up the wall as high as is comfortable.',
        'Hold briefly, then walk the fingers back down.'
      ],
      tips: ['Mark your highest point with a sticky note to track progress.'],
      caution: 'Do not shrug or lean to cheat the height. Stop if pain is sharp.',
      dose: { sets: 1, reps: 10, hold: 3, perDay: 2 },
      fig: { view: 'side', focus: ['armR'], props: [{ t: 'wall', side: 'front', gap: 1.5, h: 160 }], poses: [
        p('standSide', { armR: [20, 155] }),
        p('standSide', { armR: [158, 160] })
      ] }
    },
    {
      id: 'sh-supine-flexion-stick', name: 'Assisted arm raise (lying, with a stick)', region: 'shoulder', area: 'Shoulder flexion', type: 'mobility',
      position: 'Lying on back', equipment: ['Stick, cane or broom handle'],
      summary: 'Use both hands on a stick to lift the arms overhead, with the good arm helping.',
      steps: [
        'Lie on your back with your knees bent.',
        'Hold a stick with both hands, shoulder-width apart, resting on your thighs.',
        'Keeping your elbows straight, use your good arm to help lift the stick up and over your head.',
        'Go only as far as is comfortable, then lower slowly.'
      ],
      caution: 'Your good arm does most of the work. Stop if pain is sharp.',
      dose: { sets: 1, reps: 10, hold: 3, perDay: 2 },
      fig: { view: 'side', focus: ['armR'], poses: [
        p('hook', { armR: [120, 120], armL: [120, 120] }),
        p('hook', { armR: [240, 240], armL: [240, 240] })
      ] }
    },
    {
      id: 'sh-cross-body', name: 'Cross-body shoulder stretch', region: 'shoulder', area: 'Back of shoulder', type: 'stretch',
      position: 'Sitting or standing', equipment: [],
      summary: 'Pull one arm across the chest to stretch the back of the shoulder.',
      steps: [
        'Stand or sit tall.',
        'Bring one arm across your chest at shoulder height.',
        'With your other hand, gently press the arm closer to your chest, just above the elbow.',
        'Hold the stretch, then switch sides.'
      ],
      caution: 'Hold at the elbow, not the wrist. Stop if you feel pinching at the front of the shoulder.',
      dose: { sets: 1, reps: 3, hold: 30, perDay: 2, sides: true },
      fig: { view: 'front', focus: ['armR'], poses: [
        p('standFront', {}),
        p('standFront', { armR: [-75, -80], armL: [-20, 146] })
      ] }
    },
    {
      id: 'sh-doorway-pec', name: 'Doorway chest stretch', region: 'shoulder', area: 'Chest & front of shoulder', type: 'stretch',
      position: 'Standing in a doorway', equipment: ['Doorway'],
      summary: 'Place the forearm on a door frame and step forward to stretch the chest.',
      steps: [
        'Stand in a doorway and place your forearm on the door frame, elbow at shoulder height.',
        'Step forward with one foot until you feel a stretch across your chest.',
        'Keep your chest tall and your shoulders down.',
        'Hold, then step back. Repeat on the other side.'
      ],
      tips: ['The drawing shows you from above, with both arms on the door frame. You can also stretch one side at a time.'],
      caution: 'A gentle stretch only. Stop if you feel tingling down the arm.',
      dose: { sets: 1, reps: 3, hold: 30, perDay: 2, sides: true },
      fig: { view: 'front', floor: false, focus: ['armR', 'armL'],
        props: [{ t: 'block', at: [43, -10.5], w: 7, h: 12 }, { t: 'block', at: [-43, -10.5], w: 7, h: 12 }],
        poses: [
          p('standFront', { tScale: 0.25, nScale: 0, hScale: 0, armR: [90, 90, 1, 0.3], armL: [-90, -90, 1, 0.3], legR: [0, 0, 0, 0.01, 0.01], legL: [0, 0, 0, 0.01, 0.01] }),
          p('standFront', { y: -16, tScale: 0.25, nScale: 0, hScale: 0, armR: [58, 58, 1, 0.3], armL: [-58, -58, 1, 0.3], legR: [0, 0, 0, 0.01, 0.01], legL: [0, 0, 0, 0.01, 0.01] })
        ] }
    },
    {
      id: 'sh-er-band', name: 'External rotation with band', region: 'shoulder', area: 'Rotator cuff', type: 'strength',
      position: 'Standing', equipment: ['Resistance band'],
      summary: 'With the elbow at your side, rotate the forearm outward against a band.',
      steps: [
        'Tie the band to a door handle at waist height. Stand side-on, holding the band with the hand furthest from the door.',
        'Keep your elbow bent at 90 degrees and tucked into your side. A rolled towel under the arm helps.',
        'Slowly rotate your forearm outward, away from your belly.',
        'Hold briefly, then return slowly.'
      ],
      tips: ['Keep the elbow touching your side the whole time.'],
      caution: 'Use a light band. It should feel like work, not pain.',
      dose: { sets: 2, reps: 10, hold: 2, perDay: 1, sides: true },
      fig: { view: 'front', focus: ['armR'], props: [{ t: 'band', from: 'haR', to: { j: 'elR', dx: -58, dy: 6 } }], poses: [
        p('standFront', { armR: [2, -90, 1, 0.75] }),
        p('standFront', { armR: [2, 90, 1, 0.8] })
      ] }
    },
    {
      id: 'sh-ir-band', name: 'Internal rotation with band', region: 'shoulder', area: 'Rotator cuff', type: 'strength',
      position: 'Standing', equipment: ['Resistance band'],
      summary: 'With the elbow at your side, rotate the forearm inward against a band.',
      steps: [
        'Tie the band to a door handle at waist height. Stand side-on, holding the band with the hand closest to the door.',
        'Keep your elbow bent at 90 degrees and tucked into your side.',
        'Slowly rotate your forearm in toward your belly.',
        'Hold briefly, then return slowly.'
      ],
      caution: 'Use a light band. Stop if the movement is painful.',
      dose: { sets: 2, reps: 10, hold: 2, perDay: 1, sides: true },
      fig: { view: 'front', focus: ['armR'], props: [{ t: 'band', from: 'haR', to: { j: 'elR', dx: 58, dy: 6 } }], poses: [
        p('standFront', { armR: [2, 90, 1, 0.8] }),
        p('standFront', { armR: [2, -90, 1, 0.75] })
      ] }
    },
    {
      id: 'sh-abduction', name: 'Side arm raise', region: 'shoulder', area: 'Shoulder abduction', type: 'strength',
      position: 'Standing', equipment: ['Light weight (optional)'],
      summary: 'Raise the arm out to the side, up to shoulder height.',
      steps: [
        'Stand tall with your arm at your side, thumb pointing forward.',
        'Slowly lift your arm out to the side, up to shoulder height.',
        'Keep your shoulder down. Do not shrug.',
        'Lower slowly.'
      ],
      tips: ['Start with no weight. Your therapist may add a small weight later.'],
      caution: 'Stop below the point where the movement becomes painful.',
      dose: { sets: 2, reps: 10, perDay: 1, sides: true },
      fig: { view: 'front', focus: ['armR'], poses: [
        p('standFront', {}),
        p('standFront', { armR: [92, 92] })
      ] }
    },
    {
      id: 'sh-flexion', name: 'Forward arm raise', region: 'shoulder', area: 'Shoulder flexion', type: 'strength',
      position: 'Standing', equipment: ['Light weight (optional)'],
      summary: 'Raise the arm straight in front of you.',
      steps: [
        'Stand tall with your arm at your side, thumb pointing up.',
        'Keeping your elbow straight, lift your arm forward and up as high as is comfortable.',
        'Lower slowly.'
      ],
      caution: 'Do not lean back to lift higher.',
      dose: { sets: 2, reps: 10, perDay: 1, sides: true },
      fig: { view: 'side', focus: ['armR'], poses: [
        p('standSide', {}),
        p('standSide', { armR: [165, 165] })
      ] }
    },
    {
      id: 'sh-row-band', name: 'Band rows', region: 'shoulder', area: 'Upper back', type: 'strength',
      position: 'Standing or sitting', equipment: ['Resistance band'],
      summary: 'Pull a band back while squeezing the shoulder blades.',
      steps: [
        'Loop the band around a sturdy object in front of you at chest height. Hold one end in each hand.',
        'Stand tall with your arms straight out in front.',
        'Pull your elbows back, squeezing your shoulder blades together.',
        'Return slowly.'
      ],
      tips: ['Keep your shoulders down and wrists straight.'],
      caution: 'Make sure the band is anchored securely.',
      dose: { sets: 2, reps: 10, hold: 2, perDay: 1 },
      fig: { view: 'side', focus: ['armR'], props: [{ t: 'band', from: 'haR', to: { j: 'haR', dx: 34, dy: 0 } }], poses: [
        p('standSide', { armR: [90, 90], armL: [90, 90] }),
        p('standSide', { armR: [-20, 90], armL: [-20, 90] })
      ] }
    },

    /* ================= HAND & WRIST ================= */
    {
      id: 'hand-wrist-flex-ext', name: 'Wrist bends (up and down)', region: 'hand', area: 'Wrist mobility', type: 'mobility',
      position: 'Sitting at a table', equipment: ['Table'],
      summary: 'Rest the forearm on a table and bend the wrist up and down.',
      steps: [
        'Rest your forearm on a table with your hand hanging over the edge, palm down.',
        'Slowly bend your wrist up as far as is comfortable.',
        'Then let it bend down as far as is comfortable.',
        'Keep your fingers relaxed.'
      ],
      caution: 'Move within a comfortable range.',
      dose: { sets: 1, reps: 10, hold: 2, perDay: 3 },
      fig: { view: 'hand', focus: ['wrist'], props: [{ t: 'table', at: 'wrist', dx: -32, w: 64, dy: 8 }], poses: [
        p({ view: 'hand' }, { wrist: -55, mcp: 0, pip: 10, dip: 5 }),
        p({ view: 'hand' }, { wrist: 60, mcp: 10, pip: 15, dip: 5 })
      ] }
    },
    {
      id: 'hand-wrist-flexor-stretch', name: 'Wrist flexor stretch', region: 'hand', area: 'Forearm (palm side)', type: 'stretch',
      position: 'Sitting or standing', equipment: [],
      summary: 'Bend the wrist back, with the other hand helping, to stretch the inner forearm.',
      steps: [
        'Hold your arm out in front, elbow straight, palm facing up.',
        'With your other hand, gently bend your wrist down, pulling the fingers back toward you.',
        'Hold where you feel a stretch on the inside of your forearm.',
        'Release slowly.'
      ],
      caution: 'Gentle pressure only. Stop if you feel tingling in the fingers.',
      dose: { sets: 1, reps: 3, hold: 20, perDay: 3, sides: true },
      fig: { view: 'hand', focus: ['wrist', 'forearm'], poses: [
        p({ view: 'hand' }, { wrist: 0, mcp: 0, pip: 5, dip: 0 }),
        p({ view: 'hand' }, { wrist: -70, mcp: -10, pip: 0, dip: 0 })
      ] }
    },
    {
      id: 'hand-wrist-extensor-stretch', name: 'Wrist extensor stretch', region: 'hand', area: 'Forearm (back of hand side)', type: 'stretch',
      position: 'Sitting or standing', equipment: [],
      summary: 'Bend the wrist down, with the other hand helping, to stretch the outer forearm.',
      steps: [
        'Hold your arm out in front, elbow straight, palm facing down.',
        'With your other hand, gently bend your wrist down so your fingers point to the floor.',
        'Hold where you feel a stretch on the top of your forearm.',
        'Release slowly.'
      ],
      caution: 'Gentle pressure only.',
      dose: { sets: 1, reps: 3, hold: 20, perDay: 3, sides: true },
      fig: { view: 'hand', focus: ['wrist', 'forearm'], poses: [
        p({ view: 'hand' }, { wrist: 0, mcp: 0, pip: 5, dip: 0 }),
        p({ view: 'hand' }, { wrist: 72, mcp: 10, pip: 20, dip: 10 })
      ] }
    },
    {
      id: 'hand-tendon-glides', name: 'Tendon glides', region: 'hand', area: 'Fingers', type: 'mobility',
      position: 'Sitting', equipment: [],
      summary: 'Move the fingers through five positions to keep the tendons gliding.',
      steps: [
        'Start with your fingers straight, wrist straight.',
        'Hook fist: bend the top two finger joints, keeping the knuckles straight.',
        'Full fist: make a gentle fist with the thumb across the fingers.',
        'Tabletop: bend only at the big knuckles, keeping the fingers straight.',
        'Straight fist: bend the big and middle knuckles, keeping the fingertips straight.',
        'Return to straight fingers between each position.'
      ],
      caution: 'Move slowly and gently. No forcing.',
      dose: { sets: 1, reps: 5, hold: 3, perDay: 3 },
      fig: { view: 'hand', focus: ['fingers'], poses: [
        p({ view: 'hand' }, { wrist: 0, mcp: 0, pip: 0, dip: 0, thumb: 0 }),
        p({ view: 'hand' }, { wrist: 0, mcp: 0, pip: 95, dip: 80, thumb: 0.2 }),
        p({ view: 'hand' }, { wrist: 0, mcp: 85, pip: 100, dip: 70, thumb: 1 }),
        p({ view: 'hand' }, { wrist: 0, mcp: 85, pip: 0, dip: 0, thumb: 0.2 }),
        p({ view: 'hand' }, { wrist: 0, mcp: 85, pip: 95, dip: 0, thumb: 0.4 })
      ] }
    },
    {
      id: 'hand-fist', name: 'Make a fist', region: 'hand', area: 'Fingers', type: 'mobility',
      position: 'Sitting', equipment: [],
      summary: 'Open the fingers wide, then close them into a gentle fist.',
      steps: [
        'Hold your hand up with your fingers straight.',
        'Slowly curl your fingers into a gentle fist, thumb wrapped across the fingers.',
        'Hold, then open your hand fully and spread your fingers.'
      ],
      tips: ['Doing this in warm water can make it easier if your hand is stiff.'],
      dose: { sets: 1, reps: 10, hold: 3, perDay: 3 },
      fig: { view: 'hand', focus: ['fingers'], poses: [
        p({ view: 'hand' }, { mcp: -5, pip: 0, dip: 0, thumb: 0 }),
        p({ view: 'hand' }, { mcp: 85, pip: 100, dip: 70, thumb: 1 })
      ] }
    },
    {
      id: 'hand-finger-spread', name: 'Finger spread', region: 'hand', area: 'Fingers', type: 'mobility',
      position: 'Sitting', equipment: ['Rubber band (optional)'],
      summary: 'Spread the fingers apart, then bring them together.',
      steps: [
        'Rest your hand flat on a table, palm down.',
        'Spread your fingers as wide apart as is comfortable.',
        'Hold, then bring them back together.'
      ],
      tips: ['To make it harder, place a rubber band around your fingers.'],
      dose: { sets: 1, reps: 10, hold: 3, perDay: 3 },
      fig: { view: 'palm', focus: ['fingers'], poses: [
        p({ view: 'palm' }, { spread: 0, thumb: 0.15 }),
        p({ view: 'palm' }, { spread: 13, thumb: -0.25 })
      ] }
    },
    {
      id: 'hand-thumb-opposition', name: 'Thumb touches', region: 'hand', area: 'Thumb', type: 'mobility',
      position: 'Sitting', equipment: [],
      summary: 'Touch the thumb to the tip of each finger in turn.',
      steps: [
        'Hold your hand up with your fingers straight.',
        'Touch the tip of your thumb to the tip of your index finger, making an "O" shape.',
        'Open, then touch your thumb to each fingertip in turn, ending with the little finger.',
        'Finish by sliding your thumb across your palm toward the base of your little finger.'
      ],
      dose: { sets: 1, reps: 5, hold: 2, perDay: 3 },
      fig: { view: 'palm', focus: ['thumb'], poses: [
        p({ view: 'palm' }, { thumb: 0 }),
        p({ view: 'palm' }, { thumb: 1, bend: 0.25 })
      ] }
    },
    {
      id: 'hand-grip-squeeze', name: 'Grip squeeze', region: 'hand', area: 'Grip strength', type: 'strength',
      position: 'Sitting', equipment: ['Soft ball or putty'],
      summary: 'Squeeze a soft ball or putty to build grip strength.',
      steps: [
        'Hold a soft ball or a lump of putty in your palm.',
        'Squeeze it firmly but comfortably.',
        'Hold, then slowly relax your grip.'
      ],
      tips: ['Your therapist can suggest a softer or firmer putty.'],
      caution: 'Stop if you get pain in the wrist or thumb joint.',
      dose: { sets: 2, reps: 10, hold: 3, perDay: 2 },
      fig: { view: 'hand', focus: ['fingers'], props: [{ t: 'ball', at: { j: 'knuck', dx: 3, dy: 10 }, r: 9 }], poses: [
        p({ view: 'hand' }, { mcp: 45, pip: 60, dip: 40, thumb: 0.6 }),
        p({ view: 'hand' }, { mcp: 62, pip: 78, dip: 55, thumb: 0.9 })
      ] }
    },
    {
      id: 'hand-wrist-deviation', name: 'Wrist side-to-side', region: 'hand', area: 'Wrist mobility', type: 'mobility',
      position: 'Sitting', equipment: ['Table'],
      summary: 'Slide the hand side to side at the wrist, like a windshield wiper.',
      steps: [
        'Rest your forearm and hand flat on a table, palm down.',
        'Keeping your forearm still, slide your hand toward the thumb side.',
        'Then slide it toward the little finger side.'
      ],
      dose: { sets: 1, reps: 10, perDay: 3 },
      fig: { view: 'palm', focus: ['wrist'], poses: [
        p({ view: 'palm' }, { dev: -18 }),
        p({ view: 'palm' }, { dev: 22 })
      ] }
    },
    {
      id: 'hand-forearm-rotation', name: 'Palm up, palm down', region: 'hand', area: 'Forearm rotation', type: 'mobility',
      position: 'Sitting', equipment: ['Table'],
      summary: 'Turn the forearm so the palm faces up, then down.',
      steps: [
        'Sit with your elbow bent at 90 degrees and tucked into your side. Rest the forearm on a table if you like.',
        'Slowly turn your palm up to face the ceiling.',
        'Then turn it down to face the floor.',
        'Keep your elbow at your side the whole time.'
      ],
      tips: ['Holding a light hammer or a water bottle can add a gentle stretch at the end of the movement.', 'The drawing shows your forearm from above, turning palm down to palm up.'],
      dose: { sets: 1, reps: 10, hold: 2, perDay: 3 },
      fig: { view: 'forearm', focus: ['forearm'], props: [{ t: 'orbit', at: 'wrist', dx: -24, rx: 4.5, ry: 14 }], poses: [
        { view: 'forearm', rot: 0 },
        { view: 'forearm', rot: 180 }
      ] }
    },

    /* ================= HIP, KNEE & ANKLE ================= */
    {
      id: 'leg-ankle-pumps', name: 'Ankle pumps', region: 'leg', area: 'Ankle & circulation', type: 'mobility',
      position: 'Lying or sitting', equipment: [],
      summary: 'Point and flex the feet to keep the ankles moving and the blood flowing.',
      steps: [
        'Lie on your back or sit with your legs straight.',
        'Pull your toes up toward you.',
        'Then point your toes away from you.',
        'Keep moving smoothly up and down.'
      ],
      tips: ['Often done every hour after surgery.'],
      dose: { sets: 1, reps: 20, perDay: 6 },
      fig: { view: 'side', focus: ['footR'], poses: [
        p('supine', { legR: [90, 90, 205], legL: [90, 90, 205] }),
        p('supine', { legR: [90, 90, 125], legL: [90, 90, 125] })
      ] }
    },
    {
      id: 'leg-quad-sets', name: 'Quad sets (thigh tightening)', region: 'leg', area: 'Knee', type: 'strength',
      position: 'Lying or sitting', equipment: ['Small rolled towel'],
      summary: 'Tighten the thigh muscle to press the back of the knee down.',
      steps: [
        'Lie or sit with your legs straight and a small rolled towel under your knee.',
        'Tighten the muscle on the front of your thigh, pressing the back of your knee into the towel.',
        'Your heel may lift slightly.',
        'Hold, then relax.'
      ],
      dose: { sets: 1, reps: 10, hold: 5, perDay: 3, sides: true },
      fig: { view: 'side', focus: ['thighR'], props: [{ t: 'roll', at: 'knR', r: 5 }], poses: [
        p('supine', { legR: [96, 84, 175] }),
        p('supine', { legR: [94, 88, 172] })
      ] }
    },
    {
      id: 'leg-heel-slides', name: 'Heel slides', region: 'leg', area: 'Knee bending', type: 'mobility',
      position: 'Lying on back', equipment: ['Mat or bed'],
      summary: 'Slide the heel toward the buttock to bend the knee.',
      steps: [
        'Lie on your back with your legs straight.',
        'Slowly slide one heel toward your buttock, bending the knee as far as is comfortable.',
        'Hold, then slide the heel back down to straight.'
      ],
      tips: ['A plastic bag or towel under the heel helps it slide.'],
      dose: { sets: 1, reps: 10, hold: 3, perDay: 3, sides: true },
      fig: { view: 'side', focus: ['legR'], poses: [
        p('supine', {}),
        p('supine', { legR: [145, 25, 90] })
      ] }
    },
    {
      id: 'leg-slr', name: 'Straight leg raise', region: 'leg', area: 'Hip & thigh', type: 'strength',
      position: 'Lying on back', equipment: ['Mat or bed'],
      summary: 'Lift a straight leg while lying down to strengthen the thigh.',
      steps: [
        'Lie on your back with one knee bent and the other leg straight.',
        'Tighten the thigh of the straight leg to lock the knee.',
        'Lift the straight leg up to the height of the bent knee.',
        'Hold briefly, then lower slowly.'
      ],
      caution: 'Keep your lower back relaxed on the floor.',
      dose: { sets: 2, reps: 10, hold: 2, perDay: 1, sides: true },
      fig: { view: 'side', focus: ['legR'], poses: [
        p('supine', { legL: [150, 15, 90] }),
        p('supine', { legL: [150, 15, 90], legR: [128, 128, 218] })
      ] }
    },
    {
      id: 'leg-short-arc-quad', name: 'Short arc quads', region: 'leg', area: 'Knee', type: 'strength',
      position: 'Lying on back', equipment: ['Rolled towel or foam roll'],
      summary: 'Straighten the knee over a roll to strengthen the thigh.',
      steps: [
        'Lie on your back with a large rolled towel under your knee.',
        'Tighten your thigh and straighten your knee, lifting your heel off the floor.',
        'Hold, then slowly lower your heel.',
        'Keep the back of your knee on the roll.'
      ],
      dose: { sets: 2, reps: 10, hold: 3, perDay: 1, sides: true },
      fig: { view: 'side', focus: ['shinR'], props: [{ t: 'roll', at: 'knR', r: 8 }], poses: [
        p('supine', { legR: [112, 66, 156] }),
        p('supine', { legR: [112, 110, 196] })
      ] }
    },
    {
      id: 'leg-seated-knee-ext', name: 'Seated knee straightening', region: 'leg', area: 'Knee', type: 'strength',
      position: 'Sitting', equipment: ['Chair'],
      summary: 'Straighten the knee while sitting to strengthen the thigh.',
      steps: [
        'Sit tall in a chair with your feet flat on the floor.',
        'Slowly straighten one knee until your leg is out straight.',
        'Tighten your thigh and hold.',
        'Lower slowly.'
      ],
      tips: ['Your therapist may add an ankle weight later.'],
      dose: { sets: 2, reps: 10, hold: 3, perDay: 1, sides: true },
      fig: { view: 'side', props: CHAIR, focus: ['shinR'], poses: [
        p('sitSide', {}),
        p('sitSide', { legR: [90, 88, 178] })
      ] }
    },
    {
      id: 'leg-sit-to-stand', name: 'Sit to stand', region: 'leg', area: 'Legs & function', type: 'strength',
      position: 'Sitting', equipment: ['Sturdy chair'],
      summary: 'Stand up from a chair and sit back down slowly.',
      steps: [
        'Sit near the front of a sturdy chair with your feet flat and slightly behind your knees.',
        'Lean forward ("nose over toes") and push through your legs to stand up.',
        'Stand tall.',
        'Slowly sit back down with control. Do not drop into the chair.'
      ],
      tips: ['Use your hands on the armrests if needed. Your therapist will tell you when to try without them.'],
      caution: 'Use a chair that will not slide, with something stable nearby.',
      dose: { sets: 2, reps: 8, perDay: 1 },
      fig: { view: 'side', props: CHAIR, focus: ['thighR'], poses: [
        p('sitSide', { legR: [90, -12, 90], legL: [90, -12, 90] }),
        p('sitSide', { x: 10, torso: 132, neck: 140, armR: [90, 100], armL: [90, 100], legR: [72, -22, 90], legL: [72, -22, 90] }),
        p('standSide', { x: 28 })
      ] }
    },
    {
      id: 'leg-mini-squat', name: 'Mini squats', region: 'leg', area: 'Knee & hip', type: 'strength',
      position: 'Standing', equipment: ['Counter or chair for support'],
      summary: 'Bend the knees slightly while standing to strengthen the legs.',
      steps: [
        'Stand with your feet hip-width apart, holding a counter for balance.',
        'Bend your knees and push your hips back slightly, as if starting to sit.',
        'Keep your knees in line with your toes and your heels on the floor.',
        'Hold, then stand back up.'
      ],
      caution: 'Only bend as far as is comfortable for your knees.',
      dose: { sets: 2, reps: 10, hold: 2, perDay: 1 },
      fig: { view: 'side', focus: ['thighR'], poses: [
        p('standSide', { armR: [80, 80], armL: [80, 80] }),
        p('standSide', { x: -9, torso: 160, neck: 170, armR: [95, 90], armL: [95, 90], legR: [50, -30, 90], legL: [50, -30, 90] })
      ] }
    },
    {
      id: 'leg-calf-raise', name: 'Heel raises', region: 'leg', area: 'Calf & ankle', type: 'strength',
      position: 'Standing', equipment: ['Counter or chair for support'],
      summary: 'Rise up onto the toes to strengthen the calves.',
      steps: [
        'Stand tall holding a counter or chair back for balance.',
        'Slowly rise up onto your toes, lifting your heels as high as is comfortable.',
        'Hold, then lower slowly.'
      ],
      tips: ['To make it harder, your therapist may suggest one leg at a time.'],
      dose: { sets: 2, reps: 10, hold: 2, perDay: 1 },
      fig: { view: 'side', focus: ['footR', 'shinR'], poses: [
        p('standSide', { armR: [70, 75] }),
        p('standSide', { armR: [70, 75], legR: [0, 0, 40], legL: [0, 0, 40] })
      ] }
    },
    {
      id: 'leg-hamstring-towel', name: 'Hamstring stretch with towel', region: 'leg', area: 'Back of thigh', type: 'stretch',
      position: 'Lying on back', equipment: ['Towel or strap'],
      summary: 'Lift a straight leg with a towel around the foot to stretch the back of the thigh.',
      steps: [
        'Lie on your back. Loop a towel around the ball of one foot.',
        'Keeping the knee straight, use the towel to gently lift the leg until you feel a stretch behind the thigh.',
        'Keep the other leg flat or bent, whichever is more comfortable.',
        'Hold, then lower slowly.'
      ],
      caution: 'Stop if you feel tingling down the leg.',
      dose: { sets: 1, reps: 3, hold: 30, perDay: 2, sides: true },
      fig: { view: 'side', focus: ['legR'], props: [{ t: 'towel', from: 'haR', to: 'toR' }], poses: [
        p('supine', { armR: [120, 140], armL: [120, 140], legR: [100, 100, 190] }),
        p('supine', { armR: [168, 150], armL: [168, 150], legR: [158, 158, 248] })
      ] }
    },
    {
      id: 'leg-quad-stretch', name: 'Standing quad stretch', region: 'leg', area: 'Front of thigh', type: 'stretch',
      position: 'Standing', equipment: ['Counter or chair for support'],
      summary: 'Bend the knee and hold the ankle to stretch the front of the thigh.',
      steps: [
        'Stand tall, holding a counter or chair with one hand.',
        'Bend one knee and bring your heel toward your buttock. Hold your ankle with your hand.',
        'Keep your knees side by side and your back straight.',
        'Hold, then lower the foot slowly.'
      ],
      tips: ['Use a towel around your ankle if you cannot reach it.'],
      caution: 'Do not force the knee to bend.',
      dose: { sets: 1, reps: 3, hold: 30, perDay: 2, sides: true },
      fig: { view: 'side', focus: ['thighR'], poses: [
        p('standSide', { armL: [60, 70] }),
        p('standSide', { armL: [60, 70], armR: [-14, -14], legR: [0, -160, -95] })
      ] }
    },
    {
      id: 'leg-calf-stretch-wall', name: 'Calf stretch at wall', region: 'leg', area: 'Calf', type: 'stretch',
      position: 'Standing, facing a wall', equipment: ['Wall'],
      summary: 'Lean into a wall with one leg back to stretch the calf.',
      steps: [
        'Stand facing a wall with your hands on it at shoulder height.',
        'Step one foot back, keeping that leg straight and the heel on the floor.',
        'Bend your front knee and lean toward the wall until you feel a stretch in the back calf.',
        'Hold, then switch legs.'
      ],
      tips: ['Keep your back toes pointing forward.'],
      dose: { sets: 1, reps: 3, hold: 30, perDay: 2, sides: true },
      fig: { view: 'side', focus: ['legL'], props: [{ t: 'wall', side: 'front', gap: 1, h: 160 }], poses: [
        p('standSide', { torso: 172, armR: [100, 95], armL: [100, 95], legR: [10, -5, 90], legL: [-18, -18, 90] }),
        p('standSide', { torso: 160, armR: [110, 100], armL: [110, 100], legR: [28, -14, 90], legL: [-26, -26, 90] })
      ] }
    },
    {
      id: 'leg-hip-flexor-stretch', name: 'Kneeling hip flexor stretch', region: 'leg', area: 'Front of hip', type: 'stretch',
      position: 'Half-kneeling', equipment: ['Cushion for the knee'],
      summary: 'Kneel on one knee and shift forward to stretch the front of the hip.',
      steps: [
        'Kneel on one knee on a cushion, with the other foot flat in front of you.',
        'Keep your body upright and tighten your stomach.',
        'Gently shift your hips forward until you feel a stretch at the front of the back hip.',
        'Hold, then switch sides.'
      ],
      caution: 'Hold onto a chair for balance if needed. Skip this if kneeling hurts.',
      dose: { sets: 1, reps: 3, hold: 30, perDay: 2, sides: true },
      fig: { view: 'side', focus: ['thighL'], poses: [
        p('standSide', { legR: [88, 0, 90], legL: [0, 270, 270] }),
        p('standSide', { legR: [88, -21, 90], legL: [-20, 270, 270] })
      ] }
    },
    {
      id: 'leg-sidelying-abduction', name: 'Side-lying leg lift', region: 'leg', area: 'Side of hip', type: 'strength',
      position: 'Lying on side', equipment: ['Mat or bed'],
      summary: 'Lift the top leg while lying on your side, to strengthen the side of the hip.',
      steps: [
        'Lie on your side with your bottom knee bent for balance and your top leg straight.',
        'Keep your hips stacked. Do not roll backward.',
        'Lift your top leg toward the ceiling, leading with the heel.',
        'Hold briefly, then lower slowly.'
      ],
      dose: { sets: 2, reps: 10, hold: 2, perDay: 1, sides: true },
      fig: { view: 'front', focus: ['legR'], poses: [
        p('sideLying', { legL: [90, 90, 180] }),
        p('sideLying', { legL: [90, 90, 180], legR: [124, 124, 214] })
      ] }
    },
    {
      id: 'leg-clamshell', name: 'Clamshells', region: 'leg', area: 'Side of hip', type: 'strength',
      position: 'Lying on side', equipment: ['Mat or bed', 'Band (optional)'],
      summary: 'Open the top knee like a clam, keeping the feet together.',
      steps: [
        'Lie on your side with your hips and knees bent and your feet together.',
        'Keep your feet touching and your hips still.',
        'Lift your top knee as high as you can without rolling your hips back.',
        'Hold, then lower slowly.'
      ],
      tips: ['Place your top hand on your hip to check it does not roll back.'],
      dose: { sets: 2, reps: 10, hold: 2, perDay: 1, sides: true },
      fig: { view: 'front', focus: ['thighR'], poses: [
        p('sideLying', { legL: [80, 119, 119, 0.6, 0.55], legR: [85, 58, 58, 0.6, 0.6] }),
        p('sideLying', { legL: [80, 119, 119, 0.6, 0.55], legR: [110, 42, 42, 0.6, 0.6] })
      ] }
    },
    {
      id: 'leg-single-leg-balance', name: 'Single-leg balance', region: 'leg', area: 'Balance', type: 'balance',
      position: 'Standing', equipment: ['Counter or chair for safety'],
      summary: 'Stand on one leg to improve balance and ankle control.',
      steps: [
        'Stand next to a counter with one hand lightly resting on it.',
        'Lift one foot off the floor.',
        'Hold your balance, standing tall.',
        'Switch legs.'
      ],
      tips: ['As it gets easier, rest just a fingertip on the counter, then no hands.'],
      caution: 'Always have something sturdy to hold within reach.',
      dose: { sets: 1, reps: 3, hold: 30, perDay: 2, sides: true },
      fig: { view: 'side', focus: ['legL'], poses: [
        p('standSide', { armR: [40, 60] }),
        p('standSide', { armR: [40, 60], legR: [45, -20, 70] })
      ] }
    },
    {
      id: 'leg-ankle-circles', name: 'Ankle circles', region: 'leg', area: 'Ankle', type: 'mobility',
      position: 'Sitting', equipment: ['Chair'],
      summary: 'Draw slow circles with the foot to loosen the ankle.',
      steps: [
        'Sit with one foot lifted slightly off the floor.',
        'Slowly draw circles with your foot, moving only at the ankle.',
        'Do circles in one direction, then the other.'
      ],
      tips: ['You can also try "writing" the alphabet with your big toe.', 'The drawing shows the foot from the side. Your foot should trace a full circle.'],
      dose: { sets: 1, reps: 10, perDay: 3, sides: true },
      fig: { view: 'side', focus: ['footR'], props: [{ t: 'chair' }, { t: 'orbit', at: 'anR', dx: 7, dy: 2, rx: 10, ry: 9 }], poses: [
        p('sitSide', { legR: [80, 55, 165] }),
        p('sitSide', { legR: [80, 55, 128] }),
        p('sitSide', { legR: [80, 55, 92] })
      ] }
    }
  ];

  var REGIONS = [
    { id: 'neck', label: 'Neck' },
    { id: 'back', label: 'Back' },
    { id: 'shoulder', label: 'Shoulder' },
    { id: 'hand', label: 'Hand & wrist' },
    { id: 'leg', label: 'Hip, knee & ankle' }
  ];

  var TYPES = [
    { id: 'stretch', label: 'Stretch' },
    { id: 'strength', label: 'Strengthen' },
    { id: 'mobility', label: 'Mobility' },
    { id: 'balance', label: 'Balance' }
  ];

  global.HEPData = { exercises: EX, regions: REGIONS, types: TYPES };
})(window);
