"""Short words used to make human-readable pairing codes."""

import re
import secrets

WORDLIST: tuple[str, ...] = tuple(
    """
    acorn actor adapt admire adobe adopt alarm album
    alert alpine apex anchor angel ankle answer
    apron arcade arch argue armor artist aspect atlas
    attic audio august awake axiom azure badge bagel
    bamboo banner basket beacon beetle bench berry bicycle
    biscuit blanket blossom bluebird boulder branch brandy brass
    breeze brick bridge bronze broom bucket buffalo
    bundle button cabin cactus cadence camera canyon captain
    carbon carpet castle cedar celery cement center cereal
    chalk chance chapel chimney circle citrus clever cliff
    clover cobalt coffee goblet
    daring daylight dealer debris decade delta dentist desert
    device diamond dinner dolphin donkey dragon drawer drizzle
    dumpling dune eagle earth echo elbow elder envelope
    engine falcon family fender fern fever fiddle filter
    flight
    giant ginger glacier glove golden gondola gorilla
    gravel green grocery guitar hamlet hammer harbor harvest
    hazel helmet heron hidden hillside history honey horizon
    hotel humid hundred iceberg icon image impact inch
    orbit orchid orphan origin ounce outside oxygen oyster
    peanut paddle palace panda paper parcel parrot parsley
    pebble pepper person picnic pillow pilot pine planet
    plasma plastic plateau pocket pollen pony popcorn portrait
    prayer present prism pumpkin purple quartz rabbit
    racket radar radio ragtime rainbow railroad raisin raven
    recipe record redwood region ribbon river rocket rooftop
    satin sauna saucer science scooter season shadow shelter
    sheriff shuttle signal silver simple sketch skillet slumber
    tablet talent tandem target tennis thunder tiger timber
    toaster topic tortoise traffic travel trumpet tulip
    turkey twilight umbrella uphill unique vacuum otter vanish
    velvet vessel victory village violet violin visitor vivid
    volcano wagon walnut wander waterfall weasel wedding wrench
    """.split()
)

_WORD_SET = frozenset(WORDLIST)
_CODE_PATTERN = re.compile(r"([0-9]+)-([a-z]+)-([a-z]+)")


def generate_code(nameplate: str | int) -> str:
    """Return a nameplate and two independently chosen words."""
    nameplate_text = str(nameplate)
    if not nameplate_text.isascii() or not nameplate_text.isdigit():
        raise ValueError("nameplate must contain only ASCII digits")

    return f"{nameplate_text}-{secrets.choice(WORDLIST)}-{secrets.choice(WORDLIST)}"


def parse_code(code: str) -> tuple[str, str, str]:
    """Return the nameplate and two words from a pairing code."""
    if not isinstance(code, str):
        raise ValueError("code must have the form '<nameplate>-<word>-<word>'")

    match = _CODE_PATTERN.fullmatch(code)
    if match is None:
        raise ValueError("code must have the form '<nameplate>-<word>-<word>'")

    nameplate, first_word, second_word = match.group(1), match.group(2), match.group(3)
    if first_word not in _WORD_SET or second_word not in _WORD_SET:
        raise ValueError("code contains an unknown word")

    return nameplate, first_word, second_word
