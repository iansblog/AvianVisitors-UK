# Bird illustration prompt (NVIDIA FLUX text-only)

Text-only variant for FLUX.1-schnell (no reference images).

Placeholders: `{sci_name}`, `{com_name}`, `{pose}`.

---

## Prompt

Generate a {pose} {com_name} ({sci_name}) in the style of an Edo-period Japanese kachō-e woodblock print. The bird is rendered with VERY FEW MARKS. The body is essentially 2-4 flat color zones with sharp boundaries. There is almost no internal texture on the body - no feather-by-feather rendering, no pen-line stippling, no gradient shading. The bird looks like it was painted with maybe 30 brush strokes total: a few flat color zones, a few confident outline strokes, an accent stroke or two for major wing or tail markings, and that's it.

Confident sumi-e ink linework with soft watercolor washes. Earthy, restrained palette: burnt umber, ochre, indigo, vermillion, muted greens. The body should look like flat painted paper - not a textured surface, not shaded volume. If the species has subtle plumage variation (streaking, mottling, fine barring), ABSTRACT it into 2-3 broad zones rather than rendering it literally. Eye, beak, and feet drawn with crisp ink - these are the only places where confident dark line is appropriate.

The bird sits on a CONSISTENT WARM CREAM tonal background - like aged Japanese mulberry paper, a soft warm buff cream color. The cream ground fills the entire frame as the background and is identical across every print for visual consistency. This is the only background element: NO branch, NO twig, NO perch, NO leaves, NO foliage, NO substrate, NO scenery, NO sky, NO moon, NO water - only the bird floating against the cream paper ground. The perch is purely implied by toe posture - it is NEVER rendered. NO border or frame, NO text or signature.

Composition: the bird occupies one-third to one-half of the frame. Leave generous negative space (just the cream ground) around it. The image should feel sparse and confident, not packed with detail.

The ENTIRE bird must fit within the image frame: head, both wings (fully extended for flight pose), full tail, both legs, both feet, beak. Do NOT crop the wings, tail, legs, or any body part at the edge of the frame. Leave generous padding on all sides.

### Anatomy

- EXACTLY TWO wings (no more, no less - count them: one left, one right). EXACTLY TWO legs. EXACTLY ONE head. EXACTLY ONE beak. EXACTLY ONE tail.
- Posture, color, markings, and body proportions must match field-guide references for this species.
- Pay particular attention to species-specific patterns. Do NOT default to generic markings: if the species has a uniformly dark head, do NOT add a white face mask. If the species has solid wings, do NOT add white wingbars. If the species has no crest, do NOT add a crest.
- For close-relative species (multiple goldfinch, multiple jay, multiple sparrow species in the library), render the diagnostic differences clearly so the species are visibly distinguishable from each other.

### Feet

- BOTH FEET visible at the bottom of the body.
- Songbird feet are SMALL relative to the body. Tarsi (legs below the feathers) are roughly 10-15% of body height for finches/sparrows/warblers/chickadees, 15-20% for jays/thrushes/mockingbirds. For larger birds (ducks, hawks, owls), match typical proportions - typically still under 25%.
- Draw slim tarsi, small delicate toes. Do NOT exaggerate feet or claws; the bird is not a chicken or a crab.

### Pose

- PERCHED (pose 1): one wing folded against the body, the other tucked behind. Both feet visible at the bottom, toes curled gently forward as if grasping a thin perch - but the perch itself is NOT drawn. The bird floats in space, posture suggesting it's perched.
- IN FLIGHT (pose 2): both wings fully extended in a natural flapping position. Legs and feet either (a) tucked tight against the belly with toes folded out of sight, or (b) extended straight back along the line of the tail. Do NOT dangle the feet below the body with toes splayed.

### Output

Render at high resolution on a fully transparent background. Cut the bird out cleanly. No shadow, no paper texture, no caption.
