# Task: write dev questions like the hidden set

Hidden questions ask what one broad kind of intervention or condition does to one broad kind of outcome,
e.g. "What effect does mulch & surface cover have on invasive / non-native species abundance?".
Each input line gives a seed: an edge (`kind: edge`) or a random node pair (`kind: pair`).
Output one JSON line per input: {"id": <same id>, "cause": <broad cause phrase>, "outcome": <broad outcome phrase>}

- Generalise the specific node to the broad class a practitioner would name (2-8 words, lower case).
  Drop the qualifier: "Removal of buckthorn" -> "invasive shrub removal"; "Increased graminoid cover" ->
  "graminoid cover". Keep the measured attribute (cover vs richness vs biomass vs survival...).
- Be broad. The hidden set never names a species, a place, a site layout or a study detail. Replace them
  with the group a restoration manager would ask about:
  - species -> its functional or taxonomic group: "Cedar Waxwing density" -> "forest bird density";
    "Daphnia pulex complex" -> "zooplankton"; "white spruce seedlings" -> "conifer seedlings".
  - study set-ups -> the treatment itself: "non-mounded microsites within strip-cut treatment" ->
    "site preparation"; "plots 5 m from the road edge" -> "distance from roads".
  - measurement details -> the plain attribute: "ash-free dry weight periphyton biomass" -> "algal biomass".
- Stay faithful while broadening. Do not change what the variable is ("presence of deer" is "deer presence",
  not "deer browsing"). Keep distinctions that change the answer: native vs non-native, survival vs growth,
  cover vs richness vs abundance, plants vs animals.
- `ask: forward`: cause = subject, outcome = object. `ask: reverse`: cause = object, outcome = subject.
- The question becomes "What effect does <cause> have on <outcome>?" mechanically. Do not answer it.
- Optional "note". No other keys.
