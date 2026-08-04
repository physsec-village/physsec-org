"""DEF CON 34 store menu contents.

Single source of truth for the /menu page and its cart. The page renders from
this module, and `code` is what the cart's scannable barcode carries, so an
item's price and its barcode token can never drift apart.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Item:
    """One buyable line on the menu."""

    code: str
    name: str
    price: int
    sku: str | None = None
    price_suffix: str = ""
    desc: str = ""
    note: str = ""
    bullets: tuple[str, ...] = ()
    details: tuple[str, ...] = ()
    feature: bool = False
    image: str = ""


@dataclass(frozen=True)
class Group:
    """A run of items under one sub-heading."""

    title: str = ""
    tag: str = ""
    lede: str = ""
    prose: tuple[str, ...] = ()
    items: tuple[Item, ...] = ()
    table: dict | None = None


@dataclass(frozen=True)
class Section:
    """A jump-linked chunk of the menu."""

    slug: str
    title: str
    blurb: str = ""
    groups: tuple[Group, ...] = field(default_factory=tuple)


MENU: tuple[Section, ...] = (
    Section(
        slug="bypass-tools",
        title="Bypass Tools",
        groups=(
            Group(
                title="Latch Retraction Tools",
                lede="Push or pull a latch that does not have an engaged deadlatch. Try it in the Village.",
                items=(
                    Item(
                        code="BYP002",
                        image="byp002.webp",
                        name="Bare Metal Latch Slip",
                        price=5,
                        sku="PSV-BYP-002",
                    ),
                    Item(
                        code="BYP015001",
                        image="byp015001.webp",
                        name="Rubber Handle Latch Slip",
                        price=10,
                        sku="PSV-BYP-015-001",
                    ),
                    Item(
                        code="BYP006",
                        image="byp006.webp",
                        name="Keychain Latch Slip",
                        price=5,
                        sku="PSV-BYP-006",
                        desc="Fits on a keychain and great for EDC.",
                    ),
                    Item(
                        code="BYP011",
                        image="byp011.webp",
                        name="Latch Poker",
                        price=5,
                        sku="PSV-BYP-011",
                        desc="Used for retracting the latch plate — more ergonomic, but thicker.",
                    ),
                    Item(
                        code="BYP009",
                        image="byp009.webp",
                        name="Auto Entry Tool (“Slim Jim”)",
                        price=30,
                        sku="PSV-BYP-009",
                        desc="Insert this through the window slot of a car to hook into the locking mechanism and unlock the car.",
                    ),
                    Item(
                        code="BYP001",
                        image="byp001.webp",
                        name="Padlock Shims (pack of 20)",
                        price=20,
                        sku="PSV-BYP-001",
                        desc="For shimming padlocks open without a key by getting between the shackle and the locking mechanism.",
                    ),
                ),
            ),
            Group(
                title="Handle-Actuation Bypass",
                lede="Reach around a door and hit the handle on the other side.",
                items=(
                    Item(
                        code="BYP010",
                        image="byp010.webp",
                        name="Thumbturn Bypass Tool (J-Tool)",
                        price=40,
                        sku="PSV-BYP-010",
                        desc="Bypasses thumbturn deadbolts — insert through the crack of a double door or under a commercial door, and turn the thumbturn on the other side. Try it in the Village.",
                    ),
                    Item(
                        code="BYP016001",
                        image="byp016001.webp",
                        name="Double Door Tool",
                        price=25,
                        sku="PSV-BYP-016-001",
                        desc="Insert this between two doors to hit the crashbar on the other side.",
                    ),
                ),
            ),
            Group(
                title="Disassembly & Force Tools",
                items=(
                    Item(
                        code="MSC003",
                        image="msc003.webp",
                        name="Screwdriver Set",
                        price=25,
                        sku="PSV-MSC-003",
                        desc="Bits for most torx and security screws, RFID reader removal, lock disassembly, and so on — as well as electronics disassembly tools, all in a handy compact case.",
                    ),
                ),
            ),
            Group(
                title="Other Bypass Tools",
                items=(
                    Item(
                        code="BYP018001",
                        image="byp018001.webp",
                        name="Adams-Rite Commercial Door Hook",
                        price=30,
                        sku="PSV-BYP-018-001",
                        desc="This revolutionary discovery by the LockPickingLawyer exploits a vulnerability in many Adams-Rite brand commercial deadbolts — insert the hook beside the bolt and use it to catch the unlocking pin, causing the latch to retract.",
                    ),
                    Item(
                        code="BYP007",
                        image="byp007.webp",
                        name="Magnetic Sensing Probe",
                        price=10,
                        sku="PSV-BYP-007",
                        desc="Detect where a door's magnetic contact sensor is and which polarity it has. Then insert your own magnet to defeat the sensor and open the door without triggering the alarm. Try these in the Village on every door with a white “ALARM” sign over it.",
                    ),
                    Item(
                        code="BYP013",
                        image="byp013.webp",
                        name="Zener Diodes (pack of 140)",
                        price=15,
                        sku="PSV-BYP-013",
                        desc="Bypass normally-closed alarm systems that use end-of-line resistors: measure the voltage, then jumper the wires with a zener diode of that voltage in series. Includes 10 each of 3.3V, 3.9V, 4.7V, 5.1V, 6.2V, 6.8V, 8.2V, 10V, 12V, 15V, 16V, 18V, 20V and 24V.",
                    ),
                    Item(
                        code="BYP012",
                        image="byp012.webp",
                        name="Bypass & Measurement Wallet Card",
                        price=40,
                        sku="PSV-BYP-012",
                        desc="Designed in house by the Village, this stainless wallet card does 27 different things.",
                        details=(
                            "Large Latch Slip — insert behind a latch to retract it",
                            "Small Latch Slip — same as above",
                            "Latch Shove — retract latches with the bevel facing you",
                            "General Key Gauge — slide a key up as far as it goes on each cut; the number is the cut depth in thousandths of an inch",
                            "Schlage Key Gauge — slide a Schlage key down as far as it goes; the step it stops at is the cut depth",
                            "Medeco Key Gauge — general key gauge markings for Medeco depths",
                            "Kwikset Key Gauge — general key gauge markings for Kwikset depths",
                            "Pin Gauge — slide a pin (or tiny key) as high as it goes to read pin lengths in thou",
                            "Wire Gauge — slide a wire as high as it goes to read the AWG measure",
                            "Tubular Key Gauge — hold a tubular cut up to each of the eight steps to see which it matches",
                            "Medeco Biaxial Fore / Aft Gauge — place the shoulder at the “m” marking and match the cuts to the tick marks",
                            "Grid for Key Photographing — place a key on the grid and photograph it to allow perspective correction later",
                            "Keyway Photographing Hole / Lanyard Hole — photograph the keyway head on while keeping the camera in focus",
                            "Level / Plumb Bob — dangle the card from the bottom left hole; the c-clamp point at top right points vertical from it",
                            "Spanner Screwdriver — 6mm spanner screws, common on HID wall readers",
                            '⅜" Wrench — a very low quality wrench',
                            '¼" Wrench — a very low quality wrench, but smaller',
                            "Ruler — a short ruler; the wrench edge corresponds to 0",
                            'Compass — ¼" spaced holes that can be spun to make circles of ¼" increment size',
                            "Protractor — markings show the angle up from the card bottom",
                            "Medeco Pin Angle Reference — looking from above, tell left, centre and right pins apart relative to their tab in classic (90°) and biaxial (180°)",
                            "Tension Wrench — works in a pinch",
                            "Tubular Tension Wrench — insert the rectangle into the cutout and the triangle into the edge of the card",
                            "Terminal Block Jumper — jumper out enterphones and door relays to gain access",
                            "C-Clamp Remover — press into the c-clamp on the rear of a lock",
                            "Rim and Mortise Cylinder Drilling Jig — insert a key into the keyway hole; the round hole is now over the rim retaining screw. Centre punch the location, flip the card to get the other side, then drill. There is also a marking for where a mortise retaining screw will be",
                            "RFID Blocker — keep this card in your wallet and it blocks RFID reads except when touching the wallet (similar performance to other RFID wallet blockers that only do that)",
                        ),
                    ),
                ),
            ),
        ),
    ),
    Section(
        slug="lockpicking",
        title="Lockpicking & Decoding",
        groups=(
            Group(
                items=(
                    Item(
                        code="BYP003",
                        image="byp003.webp",
                        name="Auto Jigglers (set of 10)",
                        price=10,
                        sku="PSV-BYP-003",
                        desc="Unlocks many automotive and wafer locks. Try each one — chances are high it'll open the door.",
                    ),
                    Item(
                        code="BYP018",
                        image="byp018.webp",
                        name="Warded Pick Set",
                        price=10,
                        sku="PSV-BYP-018",
                        desc="Use these on warded locks as if they were the key — to hit the unlocking levers while missing the wards.",
                    ),
                    Item(
                        code="TBD003",
                        image="tbd003.webp",
                        name='Decoder Bundle — .006" and .010"',
                        price=30,
                        sku=None,
                        desc="Insert these thin shims between the wheel and housing of many combination locks to feel for the notch and deduce the combination.",
                    ),
                    Item(
                        code="MSC005",
                        image="msc005.webp",
                        name="UV Light and Pen Combo",
                        price=5,
                        sku="PSV-MSC-005",
                        desc="Detect frequently used buttons by seeing where the ink has been rubbed off — or write secret messages to your friends. There's a demo in the Village.",
                    ),
                ),
            ),
        ),
    ),
    Section(
        slug="lishi",
        title="Lishi Tools — $100 Each",
        blurb="Lishi tools are revolutionary lockpicks. If you are unfamiliar with them, we encourage you to look up some of the excellent content creators like LockPickingLawyer and LockNoob have put out.",
        groups=(
            Group(
                prose=(
                    "A Lishi simulates a key: use the numbered grid to position the pick at the exact position of each pin, then push down until you feel, hear or see the “click” of the pin being set. Once the lock is picked, the plug is turned and the key pins are trapped within it. The pick can now decode the lock — read the depths off the grid and you can make a functioning key for it.",
                    "Lishis also make picking much faster, quieter, easier to learn and easier to perform when security pins are present. The biggest drawback is that they only work in one type of lock each.",
                    "PSV has 8 models for sale at DEF CON 34, and every one is a genuine Lishi made in Mr. Li's factory. If you are new to Lishis and don't know what to get, we recommend starting with the SC4 if you live or work in North America, or the Y1 if you live elsewhere.",
                ),
                items=(
                ),
            ),
            Group(
                items=(
                    Item(
                        code="BYP014002",
                        image="byp014002.webp",
                        name="SC4 — Schlage “C” keyway, 6 pin",
                        price=100,
                        sku="PSV-BYP-014-002",
                        desc="Many residential, commercial and institutional buildings use the Schlage “C” keyway. If you only get one Lishi pick and you're in North America, it should be this one.",
                    ),
                    Item(
                        code="BYP014009",
                        image="byp014009.webp",
                        name="SC20 — Schlage “L” master keyway, 6 pin",
                        price=100,
                        sku="PSV-BYP-014-009",
                        desc="The “L” keyway fits “C”, “E”, “F”, “G” and “H”. C is by far the most common, with 98% market share. The SC20 gets all of them, but it is thin and more breakable than the SC4.",
                    ),
                    Item(
                        code="BYP014004",
                        image="byp014004.webp",
                        name="Kwikset KW5",
                        price=100,
                        sku="PSV-BYP-014-004",
                        desc="Kwikset locks are extremely common on residential and single-storefront commercial doors in North America.",
                    ),
                    Item(
                        code="BYP014023",
                        image="byp014023.webp",
                        name="American Lock AM5",
                        price=100,
                        sku="PSV-BYP-014-023",
                        desc="For use on American padlocks.",
                    ),
                    Item(
                        code="BYP014024",
                        image="byp014024.webp",
                        name="Master Lock M1",
                        price=100,
                        sku="PSV-BYP-014-024",
                        desc="Most Master brand padlocks use this keyway.",
                    ),
                    Item(
                        code="BYP014025",
                        image="byp014025.webp",
                        name="BE2 — BEST “A” keyway, 7 pin",
                        price=100,
                        sku="PSV-BYP-014-025",
                        desc="BEST locks are commonly seen in institutional and large industrial plants with extensive master keying. The “A” keyway is by far the most common.",
                    ),
                    Item(
                        code="BYP014010",
                        image="byp014010.webp",
                        name="Schlage Everest C123",
                        price=100,
                        sku="PSV-BYP-014-010",
                        desc="Schlage Everest tends to be seen in large multi-unit residential, and some institutional settings.",
                    ),
                    Item(
                        code="BYP014013",
                        image="byp014013.webp",
                        name="Yale Y1, 6 pin",
                        price=100,
                        sku="PSV-BYP-014-013",
                        desc="Yale-made locks are less common now, but the Y1 keyway is used by many Abus padlocks and is very common in Europe. If you are European and only get one Lishi, it should be this one.",
                    ),
                ),
            ),
        ),
    ),
    Section(
        slug="keyed-alike",
        title="Keyed Alike",
        blurb="All PSV keys are cut keyed-alike.",
        groups=(
            Group(
                items=(
                    Item(
                        code="TBD004",
                        name="PSV Common Keyed Alike Set[^2]",
                        price=50,
                        sku=None,
                        desc="The most common and useful keys in one set.",
                        bullets=(
                            "Handcuff Key",
                            "CH751 (many product camlocks)",
                            "EK333 (server racks)",
                            "A126 (older enterphones, other camlocks)",
                            "Cross Key (utilities, fixtures)",
                            "CC1 (golf carts)",
                            "FEO-K1 (elevator fire service)[^1]",
                            "EPCO 1 (elevator special service)",
                            "X4001 (elevator special service)",
                        ),
                        feature=True,
                    ),
                ),
            ),
            Group(
                title="Individual Keys",
                items=(
                    Item(
                        code="MSC001",
                        image="msc001.webp",
                        name="Cable Keyrings",
                        price=1,
                        sku="PSV-MSC-001",
                        desc="Nice screw-together keyrings — free with the purchase of keys or fobs.",
                    ),
                    Item(
                        code="KYS003",
                        image="kys003.webp",
                        name="Metal Handcuff Key",
                        price=5,
                        sku="PSV-KYS-003",
                        desc="In case you forget your handcuff keys at home. Works on all standard model North American handcuffs.",
                    ),
                    Item(
                        code="TBD005",
                        image="tbd005.webp",
                        name="Plastic Pop-Button Handcuff Key",
                        price=10,
                        sku=None,
                        desc="These pop onto clothing and will not set off metal detectors. Three colours: green, black and beige.",
                    ),
                    Item(
                        code="TBD006",
                        image="tbd006.webp",
                        name="Cross Key (3 colours)",
                        price=5,
                        sku=None,
                        desc="Used to secure things that don't quite need a key: streetcars, subways, gas caps, Industrial Control System boxes, garbage cans, older elevators, commercial building hose bibs, advertisement panels in bus stops, and so on. Also known as a “Sillcock”, “Water” or “Zurn” key.",
                    ),
                    Item(
                        code="KYS021",
                        image="kys021.webp",
                        name="EK333",
                        price=5,
                        sku="PSV-KYS-021",
                        desc="Server racks (Emka — very common).",
                    ),
                    Item(
                        code="KYS016005",
                        image="kys016005.webp",
                        name="CAT74 — Bobrick TP / paper towel dispensers",
                        price=5,
                        sku="PSV-KYS-016-005",
                        desc="Remember how everyone ran out of TP at the start of COVID? This is your key to a clean butt in the end-times.",
                    ),
                    Item(
                        code="KYS034",
                        image="kys034.webp",
                        name="Utility Panel Key (1416)",
                        price=5,
                        sku="PSV-KYS-034",
                        desc="Many utility and plumbing hose panels use these, as well as some paper towel dispensers.",
                    ),
                ),
            ),
            Group(
                title="Common Off-the-Shelf Cam Locks",
                lede="These keys fit locks that are sold as parts for other equipment. Since it is cheaper to make millions of the exact same lock rather than a different one for each new product, the same keys get used in many places.",
                items=(
                    Item(
                        code="KYS001",
                        image="kys001.webp",
                        name="CH751",
                        price=5,
                        sku="PSV-KYS-001",
                        desc="Gas caps, gas pumps, everything on most RVs, Dominion voting machines, many cash registers, and so on.",
                    ),
                    Item(
                        code="KYS019",
                        image="kys019.webp",
                        name="501CH",
                        price=5,
                        sku="PSV-KYS-019",
                        desc="Siemens equipment, Schindler elevators, Cutler-Hammer breaker panels, and many others.",
                    ),
                    Item(
                        code="KYS014",
                        image="kys014.webp",
                        name="Linear A126 Key",
                        price=5,
                        sku="PSV-KYS-014",
                        desc="Older Linear enterphones, automatic door openers, lab equipment lockouts, keyswitches on computers, and so on.",
                    ),
                ),
            ),
        ),
    ),
    Section(
        slug="specialty-keys",
        title="Specialty Keys",
        groups=(
            Group(
                title="Heavy Equipment Keys",
                items=(
                    Item(
                        code="TBD007",
                        name="Set of all Heavy Equipment Keys",
                        price=25,
                        sku=None,
                        feature=True,
                    ),
                    Item(
                        code="KYS018",
                        image="kys018.webp",
                        name="Golf Cart Key (CC1)",
                        price=5,
                        sku="PSV-KYS-018",
                        desc="Fits Club Car brand equipment.",
                    ),
                    Item(
                        code="KYS027",
                        image="kys027.webp",
                        name="Skyjack Scissorlift Key",
                        price=5,
                        sku="PSV-KYS-027",
                        desc="Fits Skyjack brand scissorlifts.",
                    ),
                    Item(
                        code="KYS008",
                        image="kys008.webp",
                        name="Tractor Key (1147)",
                        price=5,
                        sku="PSV-KYS-008",
                        desc="Fits Massey Ferguson, some John Deere and others.",
                    ),
                    Item(
                        code="KYS024",
                        image="kys024.webp",
                        name="Common Forklift Key (1430)",
                        price=5,
                        sku="PSV-KYS-024",
                        desc="Clark, Gehl, Yale, Hyster, Komatsu, Crown and others.",
                    ),
                    Item(
                        code="KYS030",
                        image="kys030.webp",
                        name="Mitsubishi Forklift Key",
                        price=5,
                        sku="PSV-KYS-030",
                        desc="Fits Mitsubishi forklifts.",
                    ),
                    Item(
                        code="KYS017",
                        image="kys017.webp",
                        name="CAT ignition",
                        price=5,
                        sku="PSV-KYS-017",
                        desc="Ignition and cab for newer CATs.",
                    ),
                    Item(
                        code="KYS029",
                        image="kys029.webp",
                        name="CAT disconnect",
                        price=5,
                        sku="PSV-KYS-029",
                        desc="Battery disconnect for newer CATs, ignition for older CATs.",
                    ),
                ),
            ),
            Group(
                title="Enterphone Keys",
                lede="Building intercoms — “enterphones” — are used to buzz up and access a building, but for most models all the logic resides in the unit itself, and they are keyed alike. Use the key to open the unit, then jumper out the leads or wave a magnet over the relay to unlock the door. Try it in the Village.",
                items=(
                    Item(
                        code="KYS014",
                        name="Linear A126 Key",
                        price=5,
                        sku="PSV-KYS-014",
                    ),
                    Item(
                        code="KYS020001",
                        image="kys020001.webp",
                        name="Doorking (DKS) 16120 Key",
                        price=10,
                        sku="PSV-KYS-020-001",
                    ),
                    Item(
                        code="KYS020002",
                        image="kys020002.webp",
                        name="Linear 222343 Key",
                        price=10,
                        sku="PSV-KYS-020-002",
                    ),
                    Item(
                        code="KYS020003",
                        image="kys020003.webp",
                        name="MIRCOM 549 Key",
                        price=5,
                        sku="PSV-KYS-020-003",
                    ),
                ),
            ),
            Group(
                title="Construction Keys",
                lede="Construction locks are used while a building is being built, and are supposed to be swapped out for different locks once construction is complete. This occasionally doesn't happen. If you ever see an IC core (figure 8 shape) painted black or orange (Schlage) or green (BEST), it will be keyed to one of these. We cut our Schlage construction keys on black anodised blanks so the key matches the lock.",
                items=(
                    Item(
                        code="KYS026001",
                        name="Schlage Black/Orange ICA",
                        price=10,
                        sku="PSV-KYS-026-001",
                    ),
                    Item(
                        code="KYS026003",
                        name="Schlage Black/Orange ICB",
                        price=10,
                        sku="PSV-KYS-026-003",
                    ),
                    Item(
                        code="KYS026004",
                        name="Schlage Black/Orange ICC",
                        price=10,
                        sku="PSV-KYS-026-004",
                    ),
                    Item(
                        code="TBD008",
                        image="tbd008.webp",
                        name="Set of all 3 Schlage Construction Keys",
                        price=20,
                        sku=None,
                        feature=True,
                    ),
                    Item(
                        code="KYS035001",
                        image="kys035001.webp",
                        name="BEST Green Construction Key",
                        price=10,
                        sku="PSV-KYS-035-001",
                    ),
                ),
            ),
            Group(
                title="Ford Fleet Keys",
                lede="When a large company or department orders a fleet of vehicles using the same key, Ford often keys it to one of seven keys — with 1284X being the most common. Many fleet vehicles across the continent (utility trucks, police cruisers, taxicabs) are keyed to one of these. We carry the 7 most common: 0135X, 0151X, 0576X, 1111X, 1284X, 1294X and 1435X.",
                items=(
                    Item(
                        code="TBD009",
                        image="tbd009.webp",
                        name="Individual Ford fleet key",
                        price=10,
                        sku=None,
                    ),
                    Item(
                        code="TBD010",
                        image="tbd010.webp",
                        name="Set of all 7 Ford fleet keys",
                        price=60,
                        sku=None,
                        feature=True,
                    ),
                ),
            ),
            Group(
                title="Cabinet Keys",
                items=(
                    Item(
                        code="TBD011",
                        image="tbd011.webp",
                        name="National Cabinet Key Set",
                        price=25,
                        sku=None,
                        desc="Many National Cabinet locks are keyed to one of these six, with C415A being most common. National locks are also used in other equipment like ICS boxes. We carry the 6 most common: C346A, C390A, C413A, C415A, C420A and C642A. Individual keys are $5 each.",
                    ),
                ),
            ),
            Group(
                title="New York City Keys",
                items=(
                    Item(
                        code="KYS012",
                        image="kys012.webp",
                        name="Citywide 1620 Key",
                        price=5,
                        sku="PSV-KYS-012",
                        desc="Works on some elevators, locked subway entrances, construction site key boxes and some firehouse doors in NYC.",
                    ),
                    Item(
                        code="KYS013",
                        image="kys013.webp",
                        name="Elevator 2642 Key",
                        price=5,
                        sku="PSV-KYS-013",
                        desc="Fire service for elevators in NYC; works on most fire panels too.",
                    ),
                    Item(
                        code="KYS032",
                        image="kys032.webp",
                        name="Electrical Panel Key",
                        price=5,
                        sku="PSV-KYS-032",
                        desc="Street lamp boxes and circuit breaker panels.",
                    ),
                ),
            ),
            Group(
                title="Fire and Alarm Panel Keys",
                lede="Fire and alarm panels by these manufacturers are all keyed alike.",
                items=(
                    Item(
                        code="KYS016001",
                        name="CAT15",
                        price=5,
                        sku="PSV-KYS-016-001",
                        desc="Harrington and Edward Systems Technology (EST) panels.",
                    ),
                    Item(
                        code="KYS016002",
                        name="CAT30",
                        price=5,
                        sku="PSV-KYS-016-002",
                        desc="Summit and Mircom panels.",
                    ),
                    Item(
                        code="KYS016003",
                        name="CAT45",
                        price=5,
                        sku="PSV-KYS-016-003",
                        desc="GE, Edward Systems Technology (EST) and Edwards panels.",
                    ),
                    Item(
                        code="KYS016004",
                        name="CAT60",
                        price=5,
                        sku="PSV-KYS-016-004",
                        desc="Gamewell panels.",
                    ),
                    Item(
                        code="TBD012",
                        image="tbd012.webp",
                        name="Full set of fire and alarm panel keys",
                        price=20,
                        sku=None,
                        feature=True,
                    ),
                ),
            ),
            Group(
                title="TSA Keys",
                items=(
                    Item(
                        code="TBD013",
                        image="tbd013.webp",
                        name="TSA002 and TSA007 Keys",
                        price=15,
                        sku=None,
                        desc="All TSA locks use the same keys, to allow the TSA to inspect the bag. There are 7 TSA keys, but #7 is by far the most common — 90% of newly manufactured TSA locks — and TSA007 and 002 together account for 99% of locks you'll find in use today. $10 individually.",
                    ),
                ),
            ),
            Group(
                title="Automotive Set",
                items=(
                    Item(
                        code="TBD014",
                        image="tbd014.webp",
                        name="Automotive Set",
                        price=30,
                        sku=None,
                        bullets=(
                            "1284X",
                            "Tryout Key (GM)",
                            "Tryout Key (Ford)",
                            "Tryout Key (Chrysler)",
                            "CC1 Golf Cart Key",
                        ),
                        feature=True,
                    ),
                ),
            ),
        ),
    ),
    Section(
        slug="elevator",
        title="Elevator Keys — $10 Each",
        blurb="If you only get one elevator key, it should be the EPCO1 or the X4001.",
        groups=(
            Group(
                items=(
                    Item(
                        code="TBD015",
                        name="Set of Most Common",
                        price=40,
                        sku=None,
                        bullets=(
                            "EPCO1 (most cabinets, many lockouts)",
                            "EPCO2 (some floor lockouts)",
                            "X4001 (many cabinets, lockouts)",
                            "X4002 (some floor lockouts)",
                            "FEO-K1 (national fire service)[^1]",
                        ),
                        feature=True,
                    ),
                    Item(
                        code="TBD016",
                        name="Elevator Master Set — contains everything",
                        price=180,
                        sku=None,
                        bullets=(
                            "FEO-K1[^1]",
                            "EPCO1, EPCO2, MFD-1",
                            "MAD X4001–X4008",
                            "Innovation EX511–EX515",
                            "KONE 1–5",
                        ),
                        feature=True,
                    ),
                ),
            ),
            Group(
                title="MAD Fixtures",
                tag="very common",
                items=(
                    Item(
                        code="KYS028001",
                        image="kys028001.webp",
                        name="X4001",
                        price=10,
                        sku="PSV-KYS-028-001",
                        desc="Independent service, light, fan, locked cabinet.",
                    ),
                    Item(
                        code="KYS028002",
                        name="X4002",
                        price=10,
                        sku="PSV-KYS-028-002",
                        desc="Run/stop, inspection service.",
                    ),
                    Item(
                        code="KYS028990",
                        name="Set of X4001–X4008",
                        price=70,
                        sku="PSV-KYS-028-990",
                        desc="X4003–X4008 are common for security floor lockouts.",
                        feature=True,
                    ),
                ),
            ),
            Group(
                title="EPCO Fixtures",
                tag="very common",
                items=(
                    Item(
                        code="KYS002001",
                        name="EPCO1",
                        price=10,
                        sku="PSV-KYS-002-001",
                        desc="Independent service, light, fan.",
                    ),
                    Item(
                        code="KYS002002",
                        name="EPCO2",
                        price=10,
                        sku="PSV-KYS-002-002",
                        desc="Inspection service, run/stop.",
                    ),
                    Item(
                        code="KYS002003",
                        name="MFD-1",
                        price=10,
                        sku="PSV-KYS-002-003",
                        desc="EPCO fire service.",
                    ),
                    Item(
                        code="TBD017",
                        name="Set of all 3 EPCO",
                        price=25,
                        sku=None,
                        feature=True,
                    ),
                ),
            ),
            Group(
                title="KONE Fixtures",
                tag="semi-common",
                items=(
                    Item(
                        code="KYS025001",
                        name="KONE1",
                        price=10,
                        sku="PSV-KYS-025-001",
                        desc="Run/stop, inspection key.",
                    ),
                    Item(
                        code="KYS025002",
                        name="KONE2",
                        price=10,
                        sku="PSV-KYS-025-002",
                        desc="Light/fan, locked cabinet.",
                    ),
                    Item(
                        code="KYS025003",
                        name="KONE3",
                        price=10,
                        sku="PSV-KYS-025-003",
                        desc="Fire service.",
                    ),
                    Item(
                        code="KYS025004",
                        name="KONE4",
                        price=10,
                        sku="PSV-KYS-025-004",
                        desc="Independent service.",
                    ),
                    Item(
                        code="KYS025005",
                        name="KONE5",
                        price=10,
                        sku="PSV-KYS-025-005",
                        desc="Floor lockout.",
                    ),
                    Item(
                        code="TBD018",
                        image="tbd018.webp",
                        name="Set of KONE 1–5",
                        price=40,
                        sku=None,
                        feature=True,
                    ),
                ),
            ),
            Group(
                title="Innovation Fixtures",
                tag="semi-common",
                items=(
                    Item(
                        code="KYS022001",
                        name="EX511",
                        price=10,
                        sku="PSV-KYS-022-001",
                        desc="Light.",
                    ),
                    Item(
                        code="KYS022005",
                        name="EX512",
                        price=10,
                        sku="PSV-KYS-022-005",
                        desc="Stop/run, fan.",
                    ),
                    Item(
                        code="KYS022002",
                        name="EX513",
                        price=10,
                        sku="PSV-KYS-022-002",
                        desc="Independent service, light/fan, cabinet.",
                    ),
                    Item(
                        code="KYS022003",
                        name="EX514",
                        price=10,
                        sku="PSV-KYS-022-003",
                        desc="Inspection.",
                    ),
                    Item(
                        code="KYS022004",
                        name="EX515",
                        price=10,
                        sku="PSV-KYS-022-004",
                        desc="Fire service.",
                    ),
                    Item(
                        code="TBD019",
                        name="Set of all Innovation Keys",
                        price=40,
                        sku=None,
                        feature=True,
                    ),
                ),
            ),
            Group(
                title="National Fire Service Key",
                items=(
                    Item(
                        code="KYS023",
                        name="FEO-K1[^1]",
                        price=10,
                        sku="PSV-KYS-023",
                    ),
                ),
            ),
            Group(
                title="Quick Reference",
                items=(
                ),
                table={
                    "caption": "Which elevator key operates which function, by fixture manufacturer",
                    "head": (
                        "Fixture",
                        "Ind. service",
                        "Inspection",
                        "Fire",
                        "Light",
                        "Fan",
                        "Stop",
                        "Floor lockouts",
                    ),
                    "rows": (
                        ("EPCO", "EPCO1", "EPCO2", "MFD-1", "EPCO1", "EPCO1", "EPCO2", "EPCO1, 2, 3…"),
                        ("Innovation", "EX513", "EX514", "EX515", "EX511, EX513", "EX512, EX513", "EX512", "EX516–519; rarely 520–529"),
                        ("MAD", "X4001", "X4002", "FEO-K1", "X4001", "X4001", "X4002", "X4001–X4008…"),
                        ("KONE", "KONE4", "KONE1", "KONE3", "KONE2", "KONE2", "KONE1", "KONE5"),
                    ),
                },
            ),
        ),
    ),
    Section(
        slug="gear",
        title="Other Physsec Gear & Swag",
        groups=(
            Group(
                items=(
                    Item(
                        code="RFID002002",
                        image="rfid002002.webp",
                        name="Rewriteable Fobs",
                        price=1,
                        sku="PSV-RFID-002-002",
                        desc="T5577 (125kHz low frequency) fobs — good for HID, IOProx, Indala, AWID and many others. Choose from 10 different colours.",
                    ),
                    Item(
                        code="RFID002001",
                        image="rfid002001.webp",
                        name="MiFare S50 “Chinese Magic” — Sector 0 Writable",
                        price=1,
                        sku="PSV-RFID-002-001",
                        desc="Common for hotels and some commercial buildings. Choose from 6 different colours.",
                    ),
                    Item(
                        code="MSC002",
                        image="msc002.webp",
                        name="Handcuffs",
                        price=40,
                        sku="PSV-MSC-002",
                        desc="Standard police-issue handcuffs (Chicago model 1000). Comes with 2 keys.",
                    ),
                ),
            ),
        ),
    ),
)


# Tuple order is load-bearing: marker numbers and generated IDs are positional.
FOOTNOTES: tuple[str, ...] = (
    "FEO-K1 is the national elevator fire service key. We will not sell one to "
    "just anyone — you will be vetted before we do.",
    "If we don't approve you to possess an FEO-K1, the PSV Common Keyed Alike "
    "Set without one is $40.",
)


ITEMS_BY_CODE: dict[str, Item] = {
    item.code: item
    for section in MENU
    for group in section.groups
    for item in group.items
}
