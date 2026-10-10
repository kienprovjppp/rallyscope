export const meta = {
  name: 'verify-rally-strikes',
  description: 'Independently verify each candidate strike in the rally from image strips, then re-check disagreements',
  phases: [
    { title: 'Judge', detail: 'one agent per batch of candidate events, looking at the image strips' },
    { title: 'Second look', detail: 'adversarial re-check of events where judge and tracker disagree' },
  ],
}

const LEGEND = `Footage: PPA pickleball men's doubles, broadcast camera high behind the NEAR baseline, 29.97 fps.
Each event has one JPEG strip: 7 crops side by side (420x420 px each) for native frames f-3 .. f+3; the
frame number is printed top-left of every crop and the event frame f is printed in YELLOW. Crops are
centred on where the tracker last saw the ball. A thin RED circle marks the tracker's ball position in
that frame (it may be missing or wrong). The ball itself is a small yellow-green ball, often motion-blurred.
Thin skeletons are drawn with labels at the hips: P1 orange, P2 green (near team, both in BLUE shirts,
closer to the camera, lower in the picture), P3 pink (far team, RED shirt), P4 cyan (far team, WHITE shirt).
Skeleton labels can be wrong: judge the hitter by the BODY (shirt colour, position), then say which label
sits on that body.`

const EVENT_SCHEMA = {
  type: 'object',
  properties: {
    events: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          frame: { type: 'integer' },
          verdict: { type: 'string', enum: ['strike', 'bounce', 'none', 'unclear'] },
          contact_frame: { type: 'integer', description: 'frame number of the paddle contact or bounce; -1 if none' },
          hitter_shirt: { type: 'string', enum: ['blue-left', 'blue-right', 'red', 'white', 'none', 'unclear'], description: 'blue-left/right = the near-team player on the left/right of the two blue shirts in the full picture at that moment' },
          hitter_label: { type: 'string', enum: ['P1', 'P2', 'P3', 'P4', 'none', 'unclear'], description: 'skeleton label drawn on the hitter body (may be absent)' },
          label_on_right_body: { type: 'boolean', description: 'true if the skeleton label on the hitter body matches its shirt team (blue=P1/P2, red=P3, white=P4)' },
          confidence: { type: 'string', enum: ['high', 'medium', 'low'] },
          evidence: { type: 'string', description: 'one short sentence: what you saw in which crops' },
        },
        required: ['frame', 'verdict', 'contact_frame', 'hitter_shirt', 'hitter_label', 'label_on_right_body', 'confidence', 'evidence'],
      },
    },
  },
  required: ['events'],
}

const batches = args.batches
const judged = await pipeline(
  batches,
  (batch, _, i) => agent(
    `${LEGEND}

Look at every image below with the Read tool (they are local JPEG files) and classify each event.
- strike: a paddle visibly meets the ball (or the ball reverses right at a paddle) within the strip.
- bounce: the ball touches the court surface (a sharp change of direction at ground level, no paddle near).
- none: the ball just flies, or the event is noise (crowd, commentary).
- unclear: you cannot tell from the strip.
Tracker hints for each event (audio = paddle-like sound ratio, turn = ball direction change in degrees,
near = player whose wrist is nearest the ball and that distance in body heights) are given only as hints;
trust the pixels over the hints. Do not invent: if the ball is not visible, say unclear.

Events:
${batch.map(e => `- frame ${e.frame}: ${e.img}  hints: audio=${e.audio_ratio ?? '-'} turn=${e.turn ?? '-'} near=${e.near ?? '-'} (${e.near_h ?? '-'}h)`).join('\n')}

Return one entry per event, same frame numbers.`,
    { label: `judge:batch${i + 1}`, phase: 'Judge', schema: EVENT_SCHEMA },
  ),
)
const all = judged.filter(Boolean).flatMap(r => r.events)
log(`judged ${all.length} events`)

// disagreements: judge vs tracker hints, or low confidence
const byFrame = Object.fromEntries(batches.flat().map(e => [e.frame, e]))
const contested = all.filter(v => {
  const e = byFrame[v.frame]
  if (!e) return false
  if (v.verdict === 'unclear' || v.confidence === 'low') return true
  if (v.verdict === 'strike' && e.near && v.hitter_label !== e.near && v.hitter_label !== 'unclear') return true
  if (v.verdict === 'strike' && !v.label_on_right_body) return true
  if (v.verdict !== 'strike' && e.audio_ratio && e.audio_ratio > 10 && e.near_h != null && e.near_h < 0.6) return true
  return false
})
log(`${contested.length} contested events go to a second look`)

let second = []
if (contested.length) {
  const r = await agent(
    `${LEGEND}

You are a skeptical second reviewer. For each event below a first reviewer gave a verdict that conflicts with
the tracker or was unsure. Open each image with the Read tool, look again from scratch, and give YOUR verdict.
Try to refute the first reviewer; keep their answer only if the pixels support it.

${contested.map(v => { const e = byFrame[v.frame]; return `- frame ${v.frame}: ${e.img}
  first reviewer: ${v.verdict} at ${v.contact_frame}, hitter ${v.hitter_shirt}/${v.hitter_label} (${v.confidence}): ${v.evidence}
  tracker hints: audio=${e.audio_ratio ?? '-'} turn=${e.turn ?? '-'} near=${e.near ?? '-'} (${e.near_h ?? '-'}h)` }).join('\n')}`,
    { label: 'second-look', phase: 'Second look', schema: EVENT_SCHEMA },
  )
  second = r ? r.events : []
}
return { judged: all, second }
